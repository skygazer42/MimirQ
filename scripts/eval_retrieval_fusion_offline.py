#!/usr/bin/env python3
"""
Offline evaluation for retrieval fusion variants (retrieval-only) via Evidence API.

Why:
- Fusion changes are subtle and can regress recall without obvious symptoms.
- This script compares multiple fusion variants on the same regression case bundle
  using the stable Evidence API contract (/api/v1/rag/retrieve).

Metrics:
- Recall, MRR, NDCG, Hit@K (computed from reference_sources vs citations)
- Abstain rate (from API response)
"""


import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

import httpx

from app.rag.evaluation.evidence_retrieve_gate import build_retrieval_gate_summary, compute_retrieval_item_meta


def _load_json(path: Path) -> Any:
    # PowerShell commonly writes UTF-8 JSON with BOM; `utf-8-sig` handles both BOM/no-BOM.
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _headers(args: argparse.Namespace) -> dict[str, str]:
    h: dict[str, str] = {"Content-Type": "application/json"}
    if args.tenant_id:
        h["X-Tenant-ID"] = str(args.tenant_id)
    if args.user_id:
        h["X-User-ID"] = str(args.user_id)
    if args.bearer:
        h["Authorization"] = f"Bearer {args.bearer}"
    return h


def coerce_case_bundle(obj: Any) -> tuple[str, list[dict[str, Any]]]:
    """
    Normalize case bundle payloads into: (dataset_id, items[]).

    Supported shapes:
    - Export bundle v1: {"schema":"mimirq.regression_cases.v1","dataset_id":"...","items":[...]}
    - Minimal bundle: {"dataset_id":"...","items":[...]}
    - Legacy: [{"dataset_id":"...","question":"...","reference_sources":[...], ...}, ...]
    """
    if isinstance(obj, dict) and isinstance(obj.get("items"), list):
        ds = str(obj.get("dataset_id") or "").strip()
        if ds:
            items = [x for x in obj.get("items") if isinstance(x, dict)]
            cleaned = [{k: v for k, v in it.items() if k != "dataset_id"} for it in items]
            return ds, cleaned
        return coerce_case_bundle(list(obj.get("items") or []))

    if isinstance(obj, list):
        items = [x for x in obj if isinstance(x, dict)]
        dsids: list[str] = []
        for it in items:
            ds = str(it.get("dataset_id") or "").strip()
            if ds and ds not in dsids:
                dsids.append(ds)
        if not dsids:
            raise ValueError("dataset_id is required in cases bundle")
        if len(dsids) > 1:
            raise ValueError("mixed dataset_id in cases bundle")
        dsid = dsids[0]
        cleaned = [{k: v for k, v in it.items() if k != "dataset_id"} for it in items]
        return dsid, cleaned

    raise ValueError("cases file must be a JSON array, or an object with { dataset_id, items: [...] }")


def _load_matrix(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    if not path.exists():
        raise FileNotFoundError(path)
    raw = _load_json(path)
    return raw if isinstance(raw, dict) else {}


def _build_variants(*, matrix: dict[str, Any], global_base: dict[str, Any]) -> list[dict[str, Any]]:
    base_raw = matrix.get("base") if isinstance(matrix.get("base"), dict) else {}
    base_label = str(base_raw.get("label") or "").strip() or "base"
    base_cfg = base_raw.get("rag_config") if isinstance(base_raw.get("rag_config"), dict) else {}

    variants_out: list[dict[str, Any]] = []

    def _add(label: str, override: dict[str, Any]) -> None:
        cfg = {**dict(global_base), **dict(base_cfg), **dict(override or {})}
        variants_out.append({"label": label, "rag_config": cfg})

    _add(base_label, {})

    raw_variants = matrix.get("variants")
    if isinstance(raw_variants, list):
        for v in raw_variants:
            if not isinstance(v, dict):
                continue
            lab = str(v.get("label") or "").strip() or "variant"
            cfg = v.get("rag_config") if isinstance(v.get("rag_config"), dict) else {}
            _add(lab, cfg)

    if len(variants_out) == 1:
        # Default comparison: current behavior vs budgeted_rrf (no other knobs).
        _add("budgeted_rrf", {"fusion_strategy": "budgeted_rrf"})

    return variants_out


def _format_md_table(rows: list[dict[str, Any]]) -> str:
    headers = [
        "variant",
        "cases",
        "recall",
        "mrr",
        "ndcg@10",
        "ndcg@20",
        "hit@10",
        "hit@20",
        "abstain",
    ]

    def _f(x: Any) -> str:
        if x is None:
            return ""
        try:
            return f"{float(x):.4f}"
        except Exception:
            return str(x)

    lines = []
    lines.append("| " + " | ".join(headers) + " |")
    lines.append("| " + " | ".join(["---"] * len(headers)) + " |")
    for r in rows:
        lines.append(
            "| "
            + " | ".join(
                [
                    str(r.get("label") or ""),
                    str(r.get("cases_used") or 0),
                    _f((r.get("summary") or {}).get("retrieval_recall")),
                    _f((r.get("summary") or {}).get("retrieval_mrr")),
                    _f((r.get("summary") or {}).get("retrieval_ndcg_at_10")),
                    _f((r.get("summary") or {}).get("retrieval_ndcg_at_20")),
                    _f((r.get("summary") or {}).get("retrieval_hit_at_10")),
                    _f((r.get("summary") or {}).get("retrieval_hit_at_20")),
                    _f((r.get("summary") or {}).get("abstain_rate")),
                ]
            )
            + " |"
        )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Offline evaluation: compare retrieval fusion variants via Evidence API.")
    p.add_argument("--cases", required=True, help="Path to regression cases JSON (bundle v1 or legacy array)")
    p.add_argument("--matrix", default="", help="Optional: JSON config defining base + variants")

    p.add_argument("--base-url", default="http://localhost:8000/api/v1", help="API base URL (default: %(default)s)")
    p.add_argument("--tenant-id", default="", help="Tenant id (X-Tenant-ID header)")
    p.add_argument("--user-id", default="", help="User id (X-User-ID header, for AUTH_MODE=header)")
    p.add_argument("--bearer", default="", help="Bearer token (Authorization: Bearer ...)")
    p.add_argument("--timeout-sec", type=float, default=30.0, help="HTTP timeout seconds (default: %(default)s)")

    # Global base rag_config defaults (variants can override via --matrix).
    p.add_argument("--top-k", type=int, default=50, help="Evidence API rag_config.top_k (default: %(default)s)")
    p.add_argument("--score-threshold", type=float, default=0.0, help="Evidence API rag_config.score_threshold (default: %(default)s)")
    p.add_argument("--retrieval-mode", default="hybrid", help="hybrid|vector|keyword|mmr (default: %(default)s)")
    p.add_argument("--retrieval-profile", default="recall50", help="recall20|recall50|coverage80 (default: %(default)s)")
    p.add_argument("--alpha", type=float, default=0.6, help="Fusion alpha (default: %(default)s)")
    p.add_argument(
        "--enable-weight-rerank",
        action="store_true",
        help="Enable keyword TF-IDF rerank (default: off; keep off to isolate fusion behavior).",
    )
    p.add_argument(
        "--enable-reranker",
        action="store_true",
        help="Enable reranker in retriever (default: off; keep off to isolate fusion behavior).",
    )

    p.add_argument("--max-cases", type=int, default=0, help="Limit number of cases (default: all)")
    p.add_argument("--out-json", default="", help="Optional: write result JSON to this path")
    p.add_argument("--out-md", default="", help="Optional: write a Markdown report table to this path")
    args = p.parse_args(argv)

    cases_path = Path(args.cases)
    if not cases_path.exists():
        print(f"[fusion-eval] ERROR: cases file not found: {cases_path}", file=sys.stderr)
        return 2

    matrix_path = Path(args.matrix) if str(args.matrix or "").strip() else None

    try:
        raw_cases = _load_json(cases_path)
        dataset_id, items = coerce_case_bundle(raw_cases)
    except Exception as exc:  # noqa: BLE001
        print(f"[fusion-eval] ERROR: failed to parse cases: {str(exc)[:200]}", file=sys.stderr)
        return 2

    if args.max_cases and int(args.max_cases) > 0:
        items = list(items)[: int(args.max_cases)]

    try:
        matrix = _load_matrix(matrix_path)
    except Exception as exc:  # noqa: BLE001
        print(f"[fusion-eval] ERROR: failed to load matrix: {str(exc)[:200]}", file=sys.stderr)
        return 2

    global_base_rag = {
        "retrieval_profile": str(args.retrieval_profile),
        "retrieval_mode": str(args.retrieval_mode),
        "top_k": int(args.top_k),
        "score_threshold": float(args.score_threshold),
        "alpha": float(args.alpha),
        "enable_weight_rerank": bool(args.enable_weight_rerank),
        "enable_reranker": bool(args.enable_reranker),
    }

    variants = _build_variants(matrix=matrix, global_base=global_base_rag)
    if len(variants) < 2:
        print("[fusion-eval] ERROR: expected at least 2 variants (base + variant)", file=sys.stderr)
        return 2

    url = str(args.base_url).rstrip("/") + "/rag/retrieve"
    timeout = httpx.Timeout(float(args.timeout_sec or 30.0))

    started = time.time()
    out_rows: list[dict[str, Any]] = []

    with httpx.Client(timeout=timeout) as client:
        for v in variants:
            label = str(v.get("label") or "").strip() or "variant"
            rag_cfg = v.get("rag_config") if isinstance(v.get("rag_config"), dict) else {}

            items_meta: list[dict[str, Any]] = []
            errors: list[str] = []
            used = 0

            for item in items:
                if not isinstance(item, dict):
                    continue
                question = str(item.get("question") or item.get("query") or "").strip()
                if not question:
                    continue
                refs = item.get("reference_sources") or []
                if not isinstance(refs, list) or not refs:
                    continue

                body = {
                    "query": question,
                    "history": [],
                    "dataset_id": str(dataset_id),
                    "document_ids": [],
                    "rag_config": dict(rag_cfg),
                }

                try:
                    r = client.post(url, headers=_headers(args), json=body)
                    r.raise_for_status()
                    payload = r.json() or {}
                except Exception as exc:  # noqa: BLE001
                    errors.append(str(exc)[:200])
                    continue

                citations = payload.get("citations") or []
                if not isinstance(citations, list):
                    citations = []

                meta = compute_retrieval_item_meta(case=item, citations=list(citations))
                meta["abstain_triggered"] = bool(payload.get("abstain_triggered"))
                meta["abstain_reason"] = payload.get("abstain_reason")
                items_meta.append(meta)
                used += 1

            summary = build_retrieval_gate_summary(items_meta)
            out_rows.append(
                {
                    "label": label,
                    "rag_config": rag_cfg,
                    "cases_used": used,
                    "errors": errors[:50],
                    "summary": summary,
                }
            )

    result = {
        "schema": "mimirq.retrieval_fusion_eval.v1",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "elapsed_sec": round(time.time() - started, 3),
        "base_url": str(args.base_url),
        "dataset_id": str(dataset_id),
        "cases_total": len(items),
        "variants": out_rows,
    }

    if args.out_json:
        _write_json(Path(args.out_json), result)

    # Always print a compact table to stdout for quick comparisons.
    print(_format_md_table(out_rows))

    if args.out_md:
        Path(args.out_md).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out_md).write_text(_format_md_table(out_rows), encoding="utf-8")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

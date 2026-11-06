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
import sys
import time
from pathlib import Path
from typing import Any

import httpx

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.rag.evaluation.evidence_retrieve_gate import (  # noqa: E402
    build_retrieval_gate_summary,
    compute_retrieval_item_meta,
)
from scripts.retrieval_ablation import _headers, _load_json, _write_json, coerce_case_bundle  # noqa: E402


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


def _build_parser() -> argparse.ArgumentParser:
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
    p.add_argument(
        "--score-threshold",
        type=float,
        default=0.0,
        help="Evidence API rag_config.score_threshold (default: %(default)s)",
    )
    p.add_argument("--retrieval-mode", default="hybrid", help="hybrid|vector|keyword|mmr (default: %(default)s)")
    p.add_argument(
        "--retrieval-profile", default="recall50", help="recall20|recall50|coverage80 (default: %(default)s)"
    )
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
    return p


def _global_base_rag_config(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "retrieval_profile": str(args.retrieval_profile),
        "retrieval_mode": str(args.retrieval_mode),
        "top_k": int(args.top_k),
        "score_threshold": float(args.score_threshold),
        "alpha": float(args.alpha),
        "enable_weight_rerank": bool(args.enable_weight_rerank),
        "enable_reranker": bool(args.enable_reranker),
    }


def _case_request(
    item: Any,
    *,
    dataset_id: str,
    rag_config: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    if not isinstance(item, dict):
        return None
    question = str(item.get("question") or item.get("query") or "").strip()
    references = item.get("reference_sources") or []
    if not question or not isinstance(references, list) or not references:
        return None
    body = {
        "query": question,
        "history": [],
        "dataset_id": dataset_id,
        "document_ids": [],
        "rag_config": dict(rag_config),
    }
    return item, body


def _retrieve_case(
    client: httpx.Client,
    *,
    url: str,
    args: argparse.Namespace,
    case: dict[str, Any],
    body: dict[str, Any],
) -> tuple[dict[str, Any] | None, str | None]:
    try:
        response = client.post(url, headers=_headers(args), json=body)
        response.raise_for_status()
        payload = response.json() or {}
    except Exception as exc:  # noqa: BLE001
        return None, str(exc)[:200]
    citations = payload.get("citations") or []
    if not isinstance(citations, list):
        citations = []
    meta = compute_retrieval_item_meta(case=case, citations=list(citations))
    meta["abstain_triggered"] = bool(payload.get("abstain_triggered"))
    meta["abstain_reason"] = payload.get("abstain_reason")
    return meta, None


def _evaluate_variant(
    client: httpx.Client,
    *,
    variant: dict[str, Any],
    items: list[dict[str, Any]],
    dataset_id: str,
    url: str,
    args: argparse.Namespace,
) -> dict[str, Any]:
    label = variant["label"]
    rag_config = variant["rag_config"]
    items_meta: list[dict[str, Any]] = []
    errors: list[str] = []
    for item in items:
        request = _case_request(item, dataset_id=dataset_id, rag_config=rag_config)
        if request is None:
            continue
        case, body = request
        meta, error = _retrieve_case(client, url=url, args=args, case=case, body=body)
        if error is not None:
            errors.append(error)
            continue
        if meta is not None:
            items_meta.append(meta)
    return {
        "label": label,
        "rag_config": rag_config,
        "cases_used": len(items_meta),
        "errors": errors[:50],
        "summary": build_retrieval_gate_summary(items_meta),
    }


def _write_outputs(args: argparse.Namespace, result: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    if args.out_json:
        _write_json(Path(args.out_json), result)
    table = _format_md_table(rows)
    print(table)
    if args.out_md:
        path = Path(args.out_md)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(table, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

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

    variants = _build_variants(matrix=matrix, global_base=_global_base_rag_config(args))
    if len(variants) < 2:
        print("[fusion-eval] ERROR: expected at least 2 variants (base + variant)", file=sys.stderr)
        return 2

    url = str(args.base_url).rstrip("/") + "/rag/retrieve"
    timeout = httpx.Timeout(float(args.timeout_sec or 30.0))

    started = time.time()
    out_rows: list[dict[str, Any]] = []

    with httpx.Client(timeout=timeout) as client:
        for variant in variants:
            out_rows.append(
                _evaluate_variant(
                    client,
                    variant=variant,
                    items=items,
                    dataset_id=dataset_id,
                    url=url,
                    args=args,
                )
            )

    result = {
        "schema": "mimirq.retrieval_fusion_eval.v1",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "elapsed_sec": round(time.time() - started, 3),
        "base_url": str(args.base_url),
        "dataset_id": dataset_id,
        "cases_total": len(items),
        "variants": out_rows,
    }

    _write_outputs(args, result, out_rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

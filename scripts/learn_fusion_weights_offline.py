#!/usr/bin/env python3
"""
Learn (fit) fusion weights offline for multi-channel retrieval via Evidence API.

This is a simple, deterministic grid-search over the simplex of channel weights.

Why:
- Weighted fusion can outperform linear/rrf on some datasets when channel reliability differs.
- We want a reproducible way to pick per-dataset weights from a labeled suite.

Inputs:
- Regression cases JSON bundle (mimirq.regression_cases.v1 or legacy list)
  - Each item must include `question` (or `query`) and `reference_sources`

Outputs:
- Best weights (JSON)
- Optional full result JSON with per-variant metrics

Example:
  python scripts/learn_fusion_weights_offline.py \\
    --cases runs/regression/cases.json \\
    --base-url http://localhost:8000/api/v1 \\
    --tenant-id <TENANT_UUID> \\
    --user-id <ACCOUNT_ID> \\
    --step 0.2 \\
    --objective mrr \\
    --out-weights runs/fusion_weights/best.json \\
    --out-json runs/fusion_weights/search.json
"""


import argparse
import json
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx

from app.rag.core.hashing import stable_hash
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


def _int_simplex_partitions(total: int, parts: int) -> Iterator[tuple[int, ...]]:
    """
    Yield non-negative integer tuples (x1..x_parts) with sum == total.
    Deterministic order: first element increases slowest.
    """
    if parts <= 1:
        yield (int(total),)
        return
    for i in range(int(total) + 1):
        for rest in _int_simplex_partitions(total - i, parts - 1):
            yield (int(i),) + tuple(rest)


def _weight_variants(*, channels: list[str], step: float) -> list[dict[str, float]]:
    ch = [str(c).strip().lower() for c in (channels or []) if str(c).strip()]
    if not ch:
        raise ValueError("channels must be non-empty")
    if len(set(ch)) != len(ch):
        raise ValueError("channels must be unique")

    step_f = float(step)
    if step_f <= 0.0 or step_f > 1.0:
        raise ValueError("step must be in (0,1]")
    k = int(round(1.0 / step_f))
    if k <= 0:
        raise ValueError("invalid step")
    # Require step to evenly divide 1 for stable integer partitioning.
    if abs(step_f * k - 1.0) > 1e-6:
        raise ValueError("step must evenly divide 1.0 (e.g., 0.5, 0.25, 0.2, 0.1)")

    out: list[dict[str, float]] = []
    for row in _int_simplex_partitions(k, len(ch)):
        weights: dict[str, float] = {}
        for key, n in zip(ch, row, strict=True):
            if int(n) <= 0:
                continue
            weights[key] = float(n) / float(k)
        if not weights:
            continue
        # Normalize (defense-in-depth against float rounding).
        s = sum(float(v) for v in weights.values())
        if s <= 0.0:
            continue
        weights = {k0: float(v0) / s for k0, v0 in weights.items()}
        # Round for stable output/labels.
        weights = {k0: round(float(v0), 6) for k0, v0 in sorted(weights.items())}
        out.append(weights)
    return out


def _objective_value(summary: dict[str, Any], objective: str) -> float:
    s = summary if isinstance(summary, dict) else {}
    key = str(objective or "").strip().lower()
    if key in ("mrr", "retrieval_mrr"):
        return float(s.get("retrieval_mrr") or 0.0)
    if key in ("recall", "retrieval_recall"):
        return float(s.get("retrieval_recall") or 0.0)
    if key in ("ndcg10", "ndcg@10", "retrieval_ndcg_at_10"):
        return float(s.get("retrieval_ndcg_at_10") or 0.0)
    if key in ("ndcg20", "ndcg@20", "retrieval_ndcg_at_20"):
        return float(s.get("retrieval_ndcg_at_20") or 0.0)
    if key in ("hit10", "hit@10", "retrieval_hit_at_10"):
        return float(s.get("retrieval_hit_at_10") or 0.0)
    if key in ("hit20", "hit@20", "retrieval_hit_at_20"):
        return float(s.get("retrieval_hit_at_20") or 0.0)
    raise ValueError(f"unknown objective: {objective}")


def _variant_sig(weights: dict[str, float]) -> str:
    parts = [f"{k}:{float(v):.6f}" for k, v in sorted((weights or {}).items())]
    return ",".join(parts)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Learn fusion weights offline via Evidence API (grid search).")
    p.add_argument("--cases", required=True, help="Path to regression cases JSON (bundle v1 or legacy array)")
    p.add_argument("--base-url", default="http://localhost:8000/api/v1", help="API base URL (default: %(default)s)")
    p.add_argument("--tenant-id", default="", help="Tenant id (X-Tenant-ID header)")
    p.add_argument("--user-id", default="", help="User id (X-User-ID header, for AUTH_MODE=header)")
    p.add_argument("--bearer", default="", help="Bearer token (Authorization: Bearer ...)")
    p.add_argument("--timeout-sec", type=float, default=30.0, help="HTTP timeout seconds (default: %(default)s)")

    p.add_argument("--step", type=float, default=0.25, help="Grid step size on simplex (default: %(default)s)")
    p.add_argument(
        "--channels",
        default="vector,bm25,lexical,sparse",
        help="Comma-separated channels to tune (default: %(default)s)",
    )
    p.add_argument(
        "--objective",
        default="mrr",
        help="Objective metric: mrr|recall|ndcg10|ndcg20|hit10|hit20 (default: %(default)s)",
    )
    p.add_argument("--max-cases", type=int, default=0, help="Limit number of cases (default: all)")
    p.add_argument("--top-k", type=int, default=50, help="Evidence API rag_config.top_k (default: %(default)s)")
    p.add_argument("--score-threshold", type=float, default=0.0, help="Evidence API rag_config.score_threshold (default: %(default)s)")
    p.add_argument("--retrieval-mode", default="hybrid", help="hybrid|vector|keyword|mmr (default: %(default)s)")
    p.add_argument("--retrieval-profile", default="recall50", help="recall20|recall50|coverage80 (default: %(default)s)")

    p.add_argument("--out-json", default="", help="Optional: write full search result JSON to this path")
    p.add_argument("--out-weights", default="", help="Optional: write best weights JSON to this path")
    p.add_argument("--top-n", type=int, default=10, help="Print top-N leaderboard rows (default: %(default)s)")
    args = p.parse_args(argv)

    cases_path = Path(args.cases)
    if not cases_path.exists():
        print(f"[fusion-learn] ERROR: cases file not found: {cases_path}", file=sys.stderr)
        return 2

    try:
        raw_cases = _load_json(cases_path)
        dataset_id, items = coerce_case_bundle(raw_cases)
    except Exception as exc:  # noqa: BLE001
        print(f"[fusion-learn] ERROR: failed to parse cases: {str(exc)[:200]}", file=sys.stderr)
        return 2

    if args.max_cases and int(args.max_cases) > 0:
        items = list(items)[: int(args.max_cases)]

    channels = [s.strip() for s in str(args.channels or "").split(",") if s.strip()]
    try:
        variants = _weight_variants(channels=channels, step=float(args.step))
    except Exception as exc:  # noqa: BLE001
        print(f"[fusion-learn] ERROR: invalid grid: {str(exc)[:200]}", file=sys.stderr)
        return 2

    url = str(args.base_url).rstrip("/") + "/rag/retrieve"
    timeout = httpx.Timeout(float(args.timeout_sec or 30.0))

    global_rag = {
        "retrieval_profile": str(args.retrieval_profile),
        "retrieval_mode": str(args.retrieval_mode),
        "top_k": int(args.top_k),
        "score_threshold": float(args.score_threshold),
        # Keep other knobs stable so the grid isolates fusion weights.
        "enable_weight_rerank": False,
        "enable_reranker": False,
        "fusion_strategy": "weighted",
    }

    started = time.time()
    results: list[dict[str, Any]] = []

    with httpx.Client(timeout=timeout) as client:
        for idx, weights in enumerate(variants, start=1):
            items_meta: list[dict[str, Any]] = []
            used = 0
            errors: list[str] = []

            rag_cfg = dict(global_rag)
            rag_cfg["fusion_weights"] = dict(weights)

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
            try:
                obj = _objective_value(summary, str(args.objective))
            except Exception:
                obj = 0.0

            results.append(
                {
                    "weights": weights,
                    "weights_hash": stable_hash(_variant_sig(weights), length=16),
                    "cases_used": used,
                    "errors": errors[:25],
                    "summary": summary,
                    "objective": float(obj),
                }
            )

            if idx == 1 or idx % 25 == 0:
                elapsed = time.time() - started
                print(
                    f"[fusion-learn] progress {idx}/{len(variants)} variants elapsed={elapsed:.1f}s",
                    file=sys.stderr,
                )

    def _sort_key(row: dict[str, Any]) -> tuple[float, float, float, float]:
        summ = row.get("summary") if isinstance(row.get("summary"), dict) else {}
        return (
            float(row.get("objective") or 0.0),
            float((summ or {}).get("retrieval_recall") or 0.0),
            float((summ or {}).get("retrieval_ndcg_at_10") or 0.0),
            float((summ or {}).get("retrieval_hit_at_10") or 0.0),
        )

    results.sort(key=_sort_key, reverse=True)
    best = results[0] if results else None
    elapsed = round(time.time() - started, 3)

    out = {
        "schema": "mimirq.fusion_weights_search.v1",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "elapsed_sec": elapsed,
        "base_url": str(args.base_url),
        "dataset_id": str(dataset_id),
        "cases_total": len(items),
        "grid": {"channels": channels, "step": float(args.step)},
        "objective": str(args.objective),
        "best": best,
        "results": results,
    }

    if args.out_json:
        _write_json(Path(args.out_json), out)

    if args.out_weights and best and isinstance(best.get("weights"), dict):
        _write_json(Path(args.out_weights), best.get("weights"))

    # Print compact leaderboard to stdout.
    top_n = max(1, int(args.top_n or 0))
    print("| rank | objective | recall | ndcg@10 | hit@10 | weights |")
    print("| --- | --- | --- | --- | --- | --- |")
    for i, row in enumerate(results[:top_n], start=1):
        summ = row.get("summary") if isinstance(row.get("summary"), dict) else {}
        w = row.get("weights") if isinstance(row.get("weights"), dict) else {}
        print(
            "| "
            + " | ".join(
                [
                    str(i),
                    f"{float(row.get('objective') or 0.0):.4f}",
                    f"{float((summ or {}).get('retrieval_recall') or 0.0):.4f}",
                    f"{float((summ or {}).get('retrieval_ndcg_at_10') or 0.0):.4f}",
                    f"{float((summ or {}).get('retrieval_hit_at_10') or 0.0):.4f}",
                    json.dumps(w, ensure_ascii=False, sort_keys=True),
                ]
            )
            + " |"
        )

    if best and isinstance(best.get("weights"), dict):
        print("\nBest weights:\n" + json.dumps(best.get("weights"), ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if best else 2


if __name__ == "__main__":
    raise SystemExit(main())


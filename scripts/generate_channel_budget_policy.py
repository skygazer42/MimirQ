#!/usr/bin/env python3

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

_POLICY_SCHEMA = "mimirq.channel_budget_policy.v1"


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return int(default)


def _hash_obj(obj: Any) -> str:
    payload = json.dumps(obj, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8", errors="ignore")).hexdigest()[:24]


def _summary(report: dict[str, Any] | None) -> dict[str, float]:
    src = report if isinstance(report, dict) else {}
    raw = src.get("summary") if isinstance(src.get("summary"), dict) else {}
    return {
        "hit_at_k": _safe_float(raw.get("hit_at_k"), 0.0),
        "mrr": _safe_float(raw.get("mrr"), 0.0),
        "p95_latency_ms": _safe_float(raw.get("p95_latency_ms"), 0.0),
    }


def _normalize_budgets_to_k(raw: dict[str, int], *, k: int) -> dict[str, int]:
    out = {
        "vector": max(0, int(raw.get("vector", 0) or 0)),
        "bm25": max(0, int(raw.get("bm25", 0) or 0)),
        "lexical": max(0, int(raw.get("lexical", 0) or 0)),
        "sparse": max(0, int(raw.get("sparse", 0) or 0)),
    }
    k0 = max(1, int(k or 1))
    total = int(sum(out.values()))
    if total <= 0:
        return {"vector": k0, "bm25": 0, "lexical": 0, "sparse": 0}
    if total <= k0:
        return out

    # Keep sparse first (explicitly calibrated channel), trim others by priority.
    overflow = total - k0
    for key in ("lexical", "bm25", "vector"):
        if overflow <= 0:
            break
        cut = min(overflow, out[key])
        out[key] -= cut
        overflow -= cut
    return out


def build_channel_budget_policy(
    *,
    benchmark_report: dict[str, Any],
    hybrid_report: dict[str, Any] | None = None,
    sparse_report: dict[str, Any] | None = None,
    colbert_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    base = _summary(benchmark_report)
    hybrid = _summary(hybrid_report)
    sparse = _summary(sparse_report)
    colbert = _summary(colbert_report)
    top_k = max(1, _safe_int((benchmark_report or {}).get("top_k"), 5))

    # Baseline keyword budgets.
    keyword_budgets = _normalize_budgets_to_k(
        {
            "vector": max(1, int(round(top_k * 0.4))),
            "bm25": max(1, int(round(top_k * 0.3))),
            "lexical": max(1, top_k - max(1, int(round(top_k * 0.4))) - max(1, int(round(top_k * 0.3)))),
            "sparse": 0,
        },
        k=top_k,
    )
    vector_budgets = _normalize_budgets_to_k(
        {
            "vector": max(1, int(round(top_k * 0.7))),
            "bm25": max(0, top_k - max(1, int(round(top_k * 0.7)))),
            "lexical": 0,
            "sparse": 0,
        },
        k=top_k,
    )
    hybrid_budgets = _normalize_budgets_to_k(
        {
            "vector": max(1, int(round(top_k * 0.5))),
            "bm25": max(1, int(round(top_k * 0.25))),
            "lexical": max(1, int(round(top_k * 0.15))),
            "sparse": max(0, top_k - int(round(top_k * 0.5)) - int(round(top_k * 0.25)) - int(round(top_k * 0.15))),
        },
        k=top_k,
    )

    triggers: list[str] = []

    # Sparse channel uplift: allocate one slot when sparse report is non-regressive.
    sparse_non_regressive = (
        sparse.get("hit_at_k", 0.0) >= base.get("hit_at_k", 0.0)
        and sparse.get("mrr", 0.0) >= base.get("mrr", 0.0)
    )
    if sparse_non_regressive:
        triggers.append("sparse_uplift")
        keyword_budgets["sparse"] = max(1, keyword_budgets.get("sparse", 0))
        keyword_budgets["vector"] = max(0, keyword_budgets.get("vector", 0) - 1)
        keyword_budgets = _normalize_budgets_to_k(keyword_budgets, k=top_k)

    # ColBERT uplift in vector mode when quality is non-regressive.
    colbert_non_regressive = (
        colbert.get("hit_at_k", 0.0) >= base.get("hit_at_k", 0.0)
        and colbert.get("mrr", 0.0) >= base.get("mrr", 0.0)
    )
    if colbert_non_regressive:
        triggers.append("colbert_uplift")
        vector_budgets["vector"] = min(top_k, max(vector_budgets.get("vector", 0), int(round(top_k * 0.8))))
        vector_budgets["bm25"] = max(0, top_k - vector_budgets["vector"])
        vector_budgets = _normalize_budgets_to_k(vector_budgets, k=top_k)

    # Hybrid latency guard: shift one quota from vector to lexical when latency is very high.
    if hybrid.get("p95_latency_ms", 0.0) > 2_000.0:
        triggers.append("hybrid_latency_guard")
        if hybrid_budgets.get("vector", 0) > 1:
            hybrid_budgets["vector"] -= 1
            hybrid_budgets["lexical"] += 1
        hybrid_budgets = _normalize_budgets_to_k(hybrid_budgets, k=top_k)

    policy = {
        "schema": _POLICY_SCHEMA,
        "top_k": int(top_k),
        "fusion_strategy": "budgeted_rrf",
        "source": {
            "benchmark_report_hash": _hash_obj(benchmark_report or {}),
            "hybrid_report_hash": (_hash_obj(hybrid_report) if isinstance(hybrid_report, dict) else None),
            "sparse_report_hash": (_hash_obj(sparse_report) if isinstance(sparse_report, dict) else None),
            "colbert_report_hash": (_hash_obj(colbert_report) if isinstance(colbert_report, dict) else None),
        },
        "summary_snapshot": {
            "benchmark": {k: round(float(v), 6) for k, v in base.items()},
            "hybrid": {k: round(float(v), 6) for k, v in hybrid.items()},
            "sparse": {k: round(float(v), 6) for k, v in sparse.items()},
            "colbert": {k: round(float(v), 6) for k, v in colbert.items()},
        },
        "triggers": triggers,
        "profiles": {
            "default": {
                "fusion_strategy": "budgeted_rrf",
                "fusion_budgets": dict(keyword_budgets),
            },
            "keyword": {
                "fusion_strategy": "budgeted_rrf",
                "fusion_budgets": dict(keyword_budgets),
                "fusion_min_scores": (
                    {"sparse": 0.01}
                    if int(keyword_budgets.get("sparse", 0) or 0) > 0
                    else {}
                ),
            },
            "vector": {
                "fusion_strategy": "budgeted_rrf",
                "fusion_budgets": dict(vector_budgets),
            },
            "hybrid": {
                "fusion_strategy": "budgeted_rrf",
                "fusion_budgets": dict(hybrid_budgets),
            },
        },
    }
    return policy


def _read_json(path: Path) -> dict[str, Any]:
    raw = path.read_text(encoding="utf-8")
    obj = json.loads(raw)
    if not isinstance(obj, dict):
        raise ValueError(f"invalid_json_object:{path}")
    return obj


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate channel budget policy from offline retrieval artifacts.")
    parser.add_argument("--benchmark-report", required=True, help="Primary benchmark report JSON path.")
    parser.add_argument("--hybrid-report", default="", help="Optional hybrid benchmark report JSON path.")
    parser.add_argument("--sparse-report", default="", help="Optional sparse benchmark report JSON path.")
    parser.add_argument("--colbert-report", default="", help="Optional ColBERT benchmark report JSON path.")
    parser.add_argument("--out", default="artifacts/channel_budget_policy.v1.json", help="Output policy JSON path.")
    args = parser.parse_args(argv)

    benchmark_path = Path(str(args.benchmark_report)).expanduser().resolve()
    if not benchmark_path.exists():
        raise SystemExit(f"benchmark_report_not_found:{benchmark_path}")
    benchmark_report = _read_json(benchmark_path)

    def _optional(path_raw: str) -> dict[str, Any] | None:
        p = Path(str(path_raw or "").strip()).expanduser().resolve() if str(path_raw or "").strip() else None
        if p is None:
            return None
        if not p.exists():
            raise SystemExit(f"optional_report_not_found:{p}")
        return _read_json(p)

    hybrid_report = _optional(str(args.hybrid_report or ""))
    sparse_report = _optional(str(args.sparse_report or ""))
    colbert_report = _optional(str(args.colbert_report or ""))

    policy = build_channel_budget_policy(
        benchmark_report=benchmark_report,
        hybrid_report=hybrid_report,
        sparse_report=sparse_report,
        colbert_report=colbert_report,
    )

    out_path = Path(str(args.out)).expanduser().resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(policy, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[channel-budget-policy] wrote {out_path}")
    print(f"[channel-budget-policy] triggers={len(list(policy.get('triggers') or []))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

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
    except (TypeError, ValueError, OverflowError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return default


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


def _normalize_budgets_to_k(budgets: dict[str, int], *, k: int) -> dict[str, int]:
    if not any(budgets.values()):
        return {"vector": k, "bm25": 0, "lexical": 0}
    vector = min(budgets["vector"], k)
    bm25 = min(budgets["bm25"], k - vector)
    lexical = min(budgets["lexical"], k - vector - bm25)
    return {"vector": vector, "bm25": bm25, "lexical": lexical}


def build_channel_budget_policy(
    *,
    benchmark_report: dict[str, Any],
    hybrid_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    base = _summary(benchmark_report)
    hybrid = _summary(hybrid_report)
    top_k = max(1, _safe_int(benchmark_report.get("top_k"), 5))

    keyword_vector = max(1, round(top_k * 0.4))
    keyword_bm25 = max(1, round(top_k * 0.3))
    keyword_budgets = _normalize_budgets_to_k(
        {
            "vector": keyword_vector,
            "bm25": keyword_bm25,
            "lexical": max(1, top_k - keyword_vector - keyword_bm25),
        },
        k=top_k,
    )
    vector = max(1, round(top_k * 0.7))
    vector_budgets = _normalize_budgets_to_k(
        {
            "vector": vector,
            "bm25": top_k - vector,
            "lexical": 0,
        },
        k=top_k,
    )
    hybrid_budgets = _normalize_budgets_to_k(
        {
            "vector": max(1, round(top_k * 0.5)),
            "bm25": max(1, round(top_k * 0.25)),
            "lexical": max(1, round(top_k * 0.15)),
        },
        k=top_k,
    )

    triggers: list[str] = []

    # Hybrid latency guard: shift one quota from vector to lexical when latency is very high.
    if hybrid["p95_latency_ms"] > 2_000.0:
        triggers.append("hybrid_latency_guard")
        if hybrid_budgets["vector"] > 1:
            hybrid_budgets["vector"] -= 1
            hybrid_budgets["lexical"] += 1

    policy = {
        "schema": _POLICY_SCHEMA,
        "top_k": top_k,
        "fusion_strategy": "budgeted_rrf",
        "source": {
            "benchmark_report_hash": _hash_obj(benchmark_report),
            "hybrid_report_hash": (_hash_obj(hybrid_report) if isinstance(hybrid_report, dict) else None),
        },
        "summary_snapshot": {
            "benchmark": {k: round(v, 6) for k, v in base.items()},
            "hybrid": {k: round(v, 6) for k, v in hybrid.items()},
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


def _read_optional_report(path_raw: str) -> dict[str, Any] | None:
    name = path_raw.strip()
    if not name:
        return None
    path = Path(name).expanduser().resolve()
    if not path.exists():
        raise SystemExit(f"optional_report_not_found:{path}")
    return _read_json(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate channel budget policy from offline retrieval artifacts.")
    parser.add_argument("--benchmark-report", required=True, help="Primary benchmark report JSON path.")
    parser.add_argument("--hybrid-report", default="", help="Optional hybrid benchmark report JSON path.")
    parser.add_argument("--out", default="artifacts/channel_budget_policy.v1.json", help="Output policy JSON path.")
    args = parser.parse_args(argv)

    benchmark_path = Path(args.benchmark_report).expanduser().resolve()
    if not benchmark_path.exists():
        raise SystemExit(f"benchmark_report_not_found:{benchmark_path}")
    benchmark_report = _read_json(benchmark_path)

    hybrid_report = _read_optional_report(args.hybrid_report)

    policy = build_channel_budget_policy(
        benchmark_report=benchmark_report,
        hybrid_report=hybrid_report,
    )

    out_path = Path(args.out).expanduser().resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(policy, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[channel-budget-policy] wrote {out_path}")
    print(f"[channel-budget-policy] triggers={len(policy['triggers'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

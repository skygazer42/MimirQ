#!/usr/bin/env python3

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

_POLICY_SCHEMA = "mimirq.adaptive_router_policy.v1"


def _resolve_path_under_cwd(raw_path: str, *, must_exist: bool) -> Path:
    raw = str(raw_path or "").strip()
    if not raw:
        raise SystemExit("path_required")

    base = Path.cwd().resolve(strict=False)
    candidate = Path(raw).expanduser()
    resolved = candidate.resolve(strict=False) if candidate.is_absolute() else (base / candidate).resolve(strict=False)
    try:
        resolved.relative_to(base)
    except Exception as exc:
        raise SystemExit(f"path_outside_cwd_not_allowed: {raw}") from exc

    if must_exist and not resolved.exists():
        raise SystemExit(f"path_not_found: {resolved}")
    return resolved


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def _stable_hash_text(text: str) -> str:
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()[:24]


def build_policy_from_benchmark_report(report: dict[str, Any]) -> dict[str, Any]:
    """
    Build a bounded adaptive-routing policy from sample benchmark artifacts.

    The output policy is deterministic and low-cardinality by design:
    - it never includes raw query strings
    - it only emits compact routing overrides
    """
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    hit_at_k = _safe_float(summary.get("hit_at_k"), 0.0)
    mrr = _safe_float(summary.get("mrr"), 0.0)
    p95_latency_ms = _safe_float(summary.get("p95_latency_ms"), 0.0)
    avg_latency_ms = _safe_float(summary.get("avg_latency_ms"), 0.0)

    rules: list[dict[str, Any]] = [
        {
            "rule_id": "log_api_keyword_fastlane",
            "when": {
                "intent_in": ["log", "api"],
                "retrieval_mode_in": ["auto", "hybrid"],
            },
            "overrides": {
                "retrieval_mode": "keyword",
                "retrieval_profile": "recall20",
                "enable_reranker": False,
                "enable_multi_query": False,
                "enable_query_alias_expansion": False,
            },
        }
    ]
    triggers: list[str] = []

    # Recall-driven boost: when benchmark quality is weak, bias FAQ/how-to into recall-first.
    if hit_at_k < 0.85 or mrr < 0.60:
        triggers.append("recall_boost")
        rules.append(
            {
                "rule_id": "faq_howto_recall_boost",
                "when": {
                    "intent_in": ["faq", "howto", "general"],
                    "query_len_bucket_in": ["medium", "long"],
                },
                "overrides": {
                    "retrieval_profile": "recall50",
                    "top_k": 50,
                },
            }
        )

    # Latency guard: if benchmark latency is high, reduce expensive expansion for long queries.
    if p95_latency_ms > 80.0 or avg_latency_ms > 40.0:
        triggers.append("latency_guard")
        rules.append(
            {
                "rule_id": "long_query_cost_guard",
                "when": {
                    "query_len_bucket_in": ["long"],
                },
                "overrides": {
                    "enable_multi_query": False,
                    "enable_query_alias_expansion": False,
                },
            }
        )

    return {
        "schema": _POLICY_SCHEMA,
        "source": {
            "report_schema": str(report.get("schema") or ""),
            "report_hash": _stable_hash_text(json.dumps(report, ensure_ascii=False, sort_keys=True)),
        },
        "summary_snapshot": {
            "hit_at_k": round(float(hit_at_k), 6),
            "mrr": round(float(mrr), 6),
            "avg_latency_ms": round(float(avg_latency_ms), 3),
            "p95_latency_ms": round(float(p95_latency_ms), 3),
        },
        "triggers": triggers,
        "rules": rules,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate adaptive retrieval router policy from benchmark artifacts.")
    parser.add_argument("--benchmark-report", required=True, help="Path to sample retrieval benchmark report JSON.")
    parser.add_argument("--out", default="artifacts/adaptive_router_policy.v1.json", help="Output policy JSON path.")
    args = parser.parse_args(argv)

    report_path = _resolve_path_under_cwd(str(args.benchmark_report), must_exist=True)
    out_path = _resolve_path_under_cwd(str(args.out), must_exist=False)
    if not report_path.exists():
        raise SystemExit(f"benchmark_report_not_found: {report_path}")

    raw = report_path.read_text(encoding="utf-8")
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise SystemExit("benchmark_report_invalid: expected JSON object")

    policy = build_policy_from_benchmark_report(payload)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(policy, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[adaptive-router-policy] wrote {out_path}")
    print(f"[adaptive-router-policy] rules={len(list(policy.get('rules') or []))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

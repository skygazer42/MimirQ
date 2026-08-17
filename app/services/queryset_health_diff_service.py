"""
Diff helpers for query-set health snapshots.

Goal:
- compare two `mimirq.queryset_health_snapshot.v1` payloads
- emit stable, compact drift summary for PR/release review
"""

from collections.abc import Mapping
from typing import Any

QUERYSET_HEALTH_DIFF_SCHEMA_V1 = "mimirq.queryset_health_diff.v1"


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or isinstance(value, bool):
            return float(default)
        return float(value)
    except Exception:
        return float(default)


def _delta(current: float, baseline: float, *, digits: int = 6) -> float:
    return round(float(current) - float(baseline), int(digits))


def _hard_case_ids(snapshot: Mapping[str, Any], *, max_ids: int) -> list[str]:
    risk = snapshot.get("risk") if isinstance(snapshot.get("risk"), Mapping) else {}
    rows = risk.get("hard_cases") if isinstance(risk.get("hard_cases"), list) else []
    out: list[str] = []
    cap = max(1, int(max_ids or 1))
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        cid = str(row.get("id") or "").strip()
        if not cid:
            continue
        if cid not in out:
            out.append(cid)
        if len(out) >= cap:
            break
    return out


def _flag_set(snapshot: Mapping[str, Any]) -> set[str]:
    raw = snapshot.get("degradation_flags")
    if not isinstance(raw, list):
        return set()
    out: set[str] = set()
    for item in raw:
        key = str(item or "").strip()
        if key:
            out.add(key)
    return out


def diff_queryset_health_snapshots(
    baseline: Mapping[str, Any],
    current: Mapping[str, Any],
    *,
    max_hard_case_ids: int = 20,
) -> dict[str, Any]:
    base_metrics = baseline.get("metrics") if isinstance(baseline.get("metrics"), Mapping) else {}
    curr_metrics = current.get("metrics") if isinstance(current.get("metrics"), Mapping) else {}
    base_risk = baseline.get("risk") if isinstance(baseline.get("risk"), Mapping) else {}
    curr_risk = current.get("risk") if isinstance(current.get("risk"), Mapping) else {}

    metric_deltas = {
        "hit_at_k_delta": _delta(
            _as_float(curr_metrics.get("hit_at_k")), _as_float(base_metrics.get("hit_at_k")), digits=6
        ),
        "mrr_delta": _delta(_as_float(curr_metrics.get("mrr")), _as_float(base_metrics.get("mrr")), digits=6),
        "ndcg_at_k_delta": _delta(
            _as_float(curr_metrics.get("ndcg_at_k")),
            _as_float(base_metrics.get("ndcg_at_k")),
            digits=6,
        ),
        "p95_latency_ms_delta": _delta(
            _as_float(curr_metrics.get("p95_latency_ms")),
            _as_float(base_metrics.get("p95_latency_ms")),
            digits=3,
        ),
        "miss_rate_delta": _delta(
            _as_float(curr_risk.get("miss_rate")), _as_float(base_risk.get("miss_rate")), digits=6
        ),
        "weak_hit_rate_delta": _delta(
            _as_float(curr_risk.get("weak_hit_rate")),
            _as_float(base_risk.get("weak_hit_rate")),
            digits=6,
        ),
    }

    base_hash = str(baseline.get("policy_hash") or "").strip()
    curr_hash = str(current.get("policy_hash") or "").strip()
    policy_changed = bool((base_hash or curr_hash) and base_hash != curr_hash)

    base_cases = set(_hard_case_ids(baseline, max_ids=max_hard_case_ids))
    curr_cases = set(_hard_case_ids(current, max_ids=max_hard_case_ids))
    added_case_ids = sorted(curr_cases - base_cases)
    removed_case_ids = sorted(base_cases - curr_cases)
    retained_case_ids = sorted(base_cases & curr_cases)

    base_flags = _flag_set(baseline)
    curr_flags = _flag_set(current)
    added_flags = sorted(curr_flags - base_flags)
    removed_flags = sorted(base_flags - curr_flags)
    retained_flags = sorted(base_flags & curr_flags)

    return {
        "schema": QUERYSET_HEALTH_DIFF_SCHEMA_V1,
        "baseline_generated_at": str(baseline.get("generated_at") or ""),
        "current_generated_at": str(current.get("generated_at") or ""),
        "policy": {
            "baseline_source": str(baseline.get("policy_source") or ""),
            "current_source": str(current.get("policy_source") or ""),
            "baseline_hash": base_hash,
            "current_hash": curr_hash,
            "changed": policy_changed,
        },
        "metric_deltas": metric_deltas,
        "hard_case_drift": {
            "added_ids": added_case_ids,
            "removed_ids": removed_case_ids,
            "retained_ids": retained_case_ids,
        },
        "degradation_flags_drift": {
            "added_flags": added_flags,
            "removed_flags": removed_flags,
            "retained_flags": retained_flags,
        },
    }


__all__ = [
    "QUERYSET_HEALTH_DIFF_SCHEMA_V1",
    "diff_queryset_health_snapshots",
]

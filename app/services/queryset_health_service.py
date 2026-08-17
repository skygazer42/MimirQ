"""
Query-set health diagnostics helpers.

Goal:
- convert benchmark outputs into a stable snapshot schema
- compute trend deltas vs previous snapshots
- maintain a bounded history for cron/nightly jobs
"""

import json
import math
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from app.rag.core.hashing import stable_hash
from app.rag.core.logging import get_logger

SNAPSHOT_SCHEMA = "mimirq.queryset_health_snapshot.v1"
DEFAULT_POLICY: dict[str, float | int] = {
    "hit_at_k_drop_threshold": 0.03,
    "mrr_drop_threshold": 0.03,
    "ndcg_drop_threshold": 0.03,
    "p95_latency_regression_ms": 20.0,
    "miss_rate_regression_threshold": 0.05,
    "weak_hit_rate_regression_threshold": 0.08,
    "weak_hit_rr_threshold": 0.2,
    "hard_cases_limit": 5,
}
_POLICY_NORMALIZERS: dict[str, Callable[[Any], float | int]] = {
    "hit_at_k_drop_threshold": lambda value: _strict_rate(value, key="hit_at_k_drop_threshold"),
    "mrr_drop_threshold": lambda value: _strict_rate(value, key="mrr_drop_threshold"),
    "ndcg_drop_threshold": lambda value: _strict_rate(value, key="ndcg_drop_threshold"),
    "p95_latency_regression_ms": lambda value: _strict_non_negative(value, key="p95_latency_regression_ms"),
    "miss_rate_regression_threshold": lambda value: _strict_rate(value, key="miss_rate_regression_threshold"),
    "weak_hit_rate_regression_threshold": lambda value: _strict_rate(value, key="weak_hit_rate_regression_threshold"),
    "weak_hit_rr_threshold": lambda value: _strict_rate(value, key="weak_hit_rr_threshold"),
    "hard_cases_limit": lambda value: _strict_positive_int(value, key="hard_cases_limit"),
}


def _as_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or isinstance(value, bool):
            return int(default)
        return int(value)
    except Exception:
        return int(default)


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or isinstance(value, bool):
            return float(default)
        return float(value)
    except Exception:
        return float(default)


def _iso_utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _normalize_ts(generated_at: str | datetime | None) -> str:
    if isinstance(generated_at, datetime):
        if generated_at.tzinfo is None:
            generated_at = generated_at.replace(tzinfo=UTC)
        return generated_at.replace(microsecond=0).isoformat()
    ts = str(generated_at or "").strip()
    return ts or _iso_utc_now()


def _metric_delta(current: float, previous: float, digits: int = 6) -> float:
    return round(float(current) - float(previous), int(digits))


def _strict_number(value: Any, *, key: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{key} must be a number")
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(f"{key} must be finite")
    return out


def _strict_rate(value: Any, *, key: str) -> float:
    out = _strict_number(value, key=key)
    if out < 0.0 or out > 1.0:
        raise ValueError(f"{key} must be within [0, 1]")
    return round(float(out), 6)


def _strict_non_negative(value: Any, *, key: str) -> float:
    out = _strict_number(value, key=key)
    if out < 0.0:
        raise ValueError(f"{key} must be >= 0")
    return round(float(out), 6)


def _strict_positive_int(value: Any, *, key: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{key} must be an integer")
    if isinstance(value, int):
        out = int(value)
    elif isinstance(value, float) and value.is_integer():
        out = int(value)
    else:
        raise ValueError(f"{key} must be an integer")
    if out < 1:
        raise ValueError(f"{key} must be >= 1")
    return out


def validate_and_normalize_queryset_health_policy(policy: Mapping[str, Any] | None) -> dict[str, float | int]:
    if policy is None:
        return dict(DEFAULT_POLICY)
    if not isinstance(policy, Mapping):
        raise ValueError("policy must be an object")

    raw = dict(policy)
    allowed = set(DEFAULT_POLICY.keys())
    unknown = sorted(str(k) for k in raw.keys() if str(k) not in allowed)
    if unknown:
        raise ValueError(f"unknown policy keys: {', '.join(unknown)}")

    resolved: dict[str, float | int] = dict(DEFAULT_POLICY)
    for key, value in raw.items():
        resolved[str(key)] = _POLICY_NORMALIZERS[str(key)](value)

    return resolved


def _resolve_policy(policy: Mapping[str, Any] | None) -> dict[str, float | int]:
    return validate_and_normalize_queryset_health_policy(policy)


def _policy_hash(policy: Mapping[str, Any]) -> str:
    payload = json.dumps(dict(policy), ensure_ascii=False, sort_keys=True)
    return stable_hash(payload, length=24)


def _clip_text(value: Any, *, max_len: int = 160) -> str:
    text = str(value or "").strip()
    if len(text) <= max_len:
        return text
    return f"{text[: max_len - 3].rstrip()}..."


def _normalize_benchmark_cases(benchmark_report: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows_raw = benchmark_report.get("cases")
    if not isinstance(rows_raw, Sequence):
        return []

    out: list[dict[str, Any]] = []
    for i, row in enumerate(rows_raw):
        if not isinstance(row, Mapping):
            continue
        qid = str(row.get("id") or f"case-{i + 1}").strip() or f"case-{i + 1}"
        out.append(
            {
                "id": qid,
                "question": _clip_text(row.get("question"), max_len=160),
                "hit_at_k": round(_as_float(row.get("hit_at_k"), 0.0), 6),
                "reciprocal_rank": round(_as_float(row.get("reciprocal_rank"), 0.0), 6),
                "ndcg_at_k": round(_as_float(row.get("ndcg_at_k"), 0.0), 6),
                "latency_ms": round(_as_float(row.get("latency_ms"), 0.0), 3),
            }
        )
    return out


def _build_case_risk(
    *,
    benchmark_report: Mapping[str, Any],
    weak_hit_rr_threshold: float = 0.2,
    hard_cases_limit: int = 5,
) -> dict[str, Any]:
    rows = _normalize_benchmark_cases(benchmark_report)
    total = int(len(rows))
    if total <= 0:
        return {
            "cases_analyzed": 0,
            "miss_count": 0,
            "miss_rate": 0.0,
            "weak_hit_count": 0,
            "weak_hit_rate": 0.0,
            "weak_hit_rr_threshold": round(float(weak_hit_rr_threshold), 6),
            "hard_cases": [],
        }

    miss_rows: list[dict[str, Any]] = []
    weak_rows: list[dict[str, Any]] = []
    for row in rows:
        hit_at_k = _as_float(row.get("hit_at_k"), 0.0)
        rr = _as_float(row.get("reciprocal_rank"), 0.0)
        if hit_at_k <= 0.0:
            miss_rows.append(row)
        if hit_at_k > 0.0 and rr <= float(weak_hit_rr_threshold):
            weak_rows.append(row)

    ranked_hard_cases = sorted(
        rows,
        key=lambda x: (
            _as_float(x.get("hit_at_k"), 0.0),
            _as_float(x.get("reciprocal_rank"), 0.0),
            _as_float(x.get("ndcg_at_k"), 0.0),
            -_as_float(x.get("latency_ms"), 0.0),
            str(x.get("id") or ""),
        ),
    )[: max(1, int(hard_cases_limit or 1))]

    hard_cases: list[dict[str, Any]] = []
    for row in ranked_hard_cases:
        hard_cases.append(
            {
                "id": str(row.get("id") or "").strip(),
                "question": _clip_text(row.get("question"), max_len=160),
                "hit_at_k": round(_as_float(row.get("hit_at_k"), 0.0), 6),
                "reciprocal_rank": round(_as_float(row.get("reciprocal_rank"), 0.0), 6),
                "ndcg_at_k": round(_as_float(row.get("ndcg_at_k"), 0.0), 6),
                "latency_ms": round(_as_float(row.get("latency_ms"), 0.0), 3),
            }
        )

    miss_rate = round(float(len(miss_rows)) / float(total), 6)
    weak_rate = round(float(len(weak_rows)) / float(total), 6)
    return {
        "cases_analyzed": total,
        "miss_count": int(len(miss_rows)),
        "miss_rate": miss_rate,
        "weak_hit_count": int(len(weak_rows)),
        "weak_hit_rate": weak_rate,
        "weak_hit_rr_threshold": round(float(weak_hit_rr_threshold), 6),
        "hard_cases": hard_cases,
    }


def build_queryset_health_snapshot(
    *,
    benchmark_report: Mapping[str, Any],
    profile_hash: str,
    previous_snapshot: Mapping[str, Any] | None = None,
    generated_at: str | datetime | None = None,
    policy: Mapping[str, Any] | None = None,
    policy_source: str | None = None,
) -> dict[str, Any]:
    resolved_policy = _resolve_policy(policy)
    policy_source_norm = str(policy_source or "").strip() or "default"
    policy_hash = _policy_hash(resolved_policy)
    summary = benchmark_report.get("summary") if isinstance(benchmark_report.get("summary"), Mapping) else {}
    prev_metrics = (
        previous_snapshot.get("metrics") if isinstance((previous_snapshot or {}).get("metrics"), Mapping) else {}
    )
    prev_risk = previous_snapshot.get("risk") if isinstance((previous_snapshot or {}).get("risk"), Mapping) else {}
    prev_policy_hash = str((previous_snapshot or {}).get("policy_hash") or "").strip()

    hit_at_k = round(_as_float(summary.get("hit_at_k"), 0.0), 6)
    mrr = round(_as_float(summary.get("mrr"), 0.0), 6)
    ndcg_at_k = round(_as_float(summary.get("ndcg_at_k"), 0.0), 6)
    avg_latency_ms = round(_as_float(summary.get("avg_latency_ms"), 0.0), 3)
    p95_latency_ms = round(_as_float(summary.get("p95_latency_ms"), 0.0), 3)
    risk = _build_case_risk(
        benchmark_report=benchmark_report,
        weak_hit_rr_threshold=_as_float(resolved_policy.get("weak_hit_rr_threshold"), 0.2),
        hard_cases_limit=_as_int(resolved_policy.get("hard_cases_limit"), 5),
    )

    trend = {
        "hit_at_k_delta": _metric_delta(hit_at_k, _as_float(prev_metrics.get("hit_at_k"), hit_at_k), 6),
        "mrr_delta": _metric_delta(mrr, _as_float(prev_metrics.get("mrr"), mrr), 6),
        "ndcg_at_k_delta": _metric_delta(ndcg_at_k, _as_float(prev_metrics.get("ndcg_at_k"), ndcg_at_k), 6),
        "p95_latency_ms_delta": _metric_delta(
            p95_latency_ms, _as_float(prev_metrics.get("p95_latency_ms"), p95_latency_ms), 3
        ),
        "miss_rate_delta": _metric_delta(
            _as_float(risk.get("miss_rate"), 0.0),
            _as_float(prev_risk.get("miss_rate"), _as_float(risk.get("miss_rate"), 0.0)),
            6,
        ),
        "weak_hit_rate_delta": _metric_delta(
            _as_float(risk.get("weak_hit_rate"), 0.0),
            _as_float(prev_risk.get("weak_hit_rate"), _as_float(risk.get("weak_hit_rate"), 0.0)),
            6,
        ),
        "policy_changed": bool(prev_policy_hash and prev_policy_hash != policy_hash),
    }

    degradation_flags: list[str] = []
    if trend["hit_at_k_delta"] <= -_as_float(resolved_policy.get("hit_at_k_drop_threshold"), 0.03):
        degradation_flags.append("hit_at_k_drop")
    if trend["mrr_delta"] <= -_as_float(resolved_policy.get("mrr_drop_threshold"), 0.03):
        degradation_flags.append("mrr_drop")
    if trend["ndcg_at_k_delta"] <= -_as_float(resolved_policy.get("ndcg_drop_threshold"), 0.03):
        degradation_flags.append("ndcg_drop")
    if trend["p95_latency_ms_delta"] >= _as_float(resolved_policy.get("p95_latency_regression_ms"), 20.0):
        degradation_flags.append("p95_latency_regression")
    if trend["miss_rate_delta"] >= _as_float(resolved_policy.get("miss_rate_regression_threshold"), 0.05):
        degradation_flags.append("miss_rate_regression")
    if trend["weak_hit_rate_delta"] >= _as_float(resolved_policy.get("weak_hit_rate_regression_threshold"), 0.08):
        degradation_flags.append("weak_hit_rate_regression")

    status = "degraded" if degradation_flags else "healthy"
    profile_hash_norm = str(profile_hash or "").strip()

    return {
        "schema": SNAPSHOT_SCHEMA,
        "generated_at": _normalize_ts(generated_at),
        "profile_hash": profile_hash_norm,
        "policy_source": policy_source_norm,
        "policy_hash": policy_hash,
        "fixture_hash": str(benchmark_report.get("fixture_hash") or "").strip(),
        "retrieval_mode": str(benchmark_report.get("retrieval_mode") or "").strip(),
        "top_k": _as_int(benchmark_report.get("top_k"), 0),
        "metrics": {
            "cases_total": _as_int(summary.get("cases_total"), 0),
            "hit_at_k": hit_at_k,
            "mrr": mrr,
            "ndcg_at_k": ndcg_at_k,
            "avg_latency_ms": avg_latency_ms,
            "p95_latency_ms": p95_latency_ms,
        },
        "risk": risk,
        "policy": resolved_policy,
        "trend": trend,
        "degradation_flags": degradation_flags,
        "status": status,
    }


def update_queryset_health_history(
    *,
    history: Sequence[Mapping[str, Any]] | None,
    current: Mapping[str, Any],
    max_items: int = 90,
) -> list[dict[str, Any]]:
    cap = max(1, int(max_items or 1))
    out: list[dict[str, Any]] = []
    for row in history or []:
        if isinstance(row, Mapping):
            out.append(dict(row))
    out.append(dict(current))

    # Keep deterministic chronological order by generated_at when present.
    out.sort(key=lambda x: str(x.get("generated_at") or ""))
    if len(out) > cap:
        out = out[-cap:]
    return out


def load_queryset_health_history(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        raw = line.strip()
        if not raw:
            continue
        try:
            obj = json.loads(raw)
        except Exception:
            get_logger(__name__).debug("Skipping item after non-critical exception", exc_info=True)
            continue
        if isinstance(obj, dict):
            rows.append(obj)
    return rows


def write_queryset_health_history(path: Path, history: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    for row in history:
        if not isinstance(row, Mapping):
            continue
        lines.append(json.dumps(dict(row), ensure_ascii=False))
    payload = "\n".join(lines)
    if payload:
        payload += "\n"
    path.write_text(payload, encoding="utf-8")

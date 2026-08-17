"""
Regression run diff helpers (pure-ish functions).

Goal: compare two RAGAS regression run summaries and return objective deltas for sharing.
"""

import math
from datetime import UTC, datetime
from typing import Any
from uuid import UUID


def _now_utc() -> datetime:
    return datetime.now(UTC)


def _as_float(v: Any) -> float | None:
    if v is None:
        return None
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        try:
            fv = float(v)
        except Exception:
            return None
        if math.isnan(fv):
            return None
        return fv
    return None


def _diff_metric(*, key: str, before: Any, after: Any) -> dict[str, Any]:
    b = _as_float(before)
    a = _as_float(after)
    delta: float | None = None
    if b is not None and a is not None:
        delta = round(float(a - b), 6)
    return {"key": str(key), "before": before, "after": after, "delta": delta}


_RETRIEVAL_DIFF_KEYS = (
    "retrieval_recall",
    "retrieval_mrr",
    "retrieval_ndcg_at_10",
    "retrieval_ndcg_at_20",
    "retrieval_hit_at_1",
    "retrieval_hit_at_3",
    "retrieval_hit_at_5",
    "retrieval_hit_at_10",
    "retrieval_hit_at_20",
    "abstain_rate",
)

_SLICE_DIFF_DIMS = (
    "file_type",
    "language",
    "directory",
    "access_mode",
    "hit_type",
    "quality",
    "pipeline_hash",
)


_DIFF_SCORE_WEIGHTS_V1: dict[str, float] = {
    # Answer-level deterministic gate signals (when present).
    "faithfulness_det": 0.35,
    "refusal_correctness": 0.25,
    # Retrieval signals (always cheap/deterministic).
    "retrieval_ndcg_at_10": 0.2,
    "retrieval_recall": 0.2,
}


def _build_diff_score(*, base_summary: dict[str, Any], target_summary: dict[str, Any]) -> dict[str, Any] | None:
    """
    Compute a compact, stable "diff score" for CI dashboards.

    We deliberately score using the *intersection* of available metrics so
    `base_score` and `target_score` remain comparable.
    """
    if not isinstance(base_summary, dict) or not isinstance(target_summary, dict):
        return None

    base_vals: dict[str, float] = {}
    target_vals: dict[str, float] = {}
    for key, w in _DIFF_SCORE_WEIGHTS_V1.items():
        if w <= 0:
            continue
        b = _as_float(base_summary.get(key))
        a = _as_float(target_summary.get(key))
        if b is None or a is None:
            continue
        base_vals[key] = float(b)
        target_vals[key] = float(a)

    used_keys = sorted(base_vals.keys())
    if not used_keys:
        return {
            "version": "1",
            "used_metric_keys": [],
            "weights": {},
            "base_score": None,
            "target_score": None,
            "delta": None,
            "base_metrics": {},
            "target_metrics": {},
        }

    weight_sum = float(sum(float(_DIFF_SCORE_WEIGHTS_V1.get(k) or 0.0) for k in used_keys))
    if weight_sum <= 0:
        weight_sum = 1.0

    weights_used = {k: round(float(_DIFF_SCORE_WEIGHTS_V1.get(k) or 0.0) / weight_sum, 6) for k in used_keys}
    base_score = sum(float(weights_used.get(k) or 0.0) * float(base_vals.get(k) or 0.0) for k in used_keys)
    target_score = sum(float(weights_used.get(k) or 0.0) * float(target_vals.get(k) or 0.0) for k in used_keys)
    delta = round(float(target_score - base_score), 6)

    return {
        "version": "1",
        "used_metric_keys": used_keys,
        "weights": weights_used,
        "base_score": round(float(base_score), 6),
        "target_score": round(float(target_score), 6),
        "delta": delta,
        "base_metrics": {k: round(float(base_vals[k]), 6) for k in used_keys},
        "target_metrics": {k: round(float(target_vals[k]), 6) for k in used_keys},
    }


def _coerce_slices(summary: dict[str, Any]) -> dict[str, Any]:
    raw = summary.get("retrieval_slices") if isinstance(summary, dict) else None
    return raw if isinstance(raw, dict) else {}


def _metric_diff_keys(*summaries: dict[str, Any]) -> list[str]:
    keys: set[str] = set()
    for src in summaries:
        if not isinstance(src, dict):
            continue
        for key in src:
            if key != "retrieval_slices":
                keys.add(str(key))
    return sorted(keys)


def _build_metric_diffs(
    *,
    base_summary: dict[str, Any],
    target_summary: dict[str, Any],
) -> list[dict[str, Any]]:
    metric_diffs: list[dict[str, Any]] = []
    for key in _metric_diff_keys(base_summary, target_summary):
        before = base_summary.get(key) if isinstance(base_summary, dict) else None
        after = target_summary.get(key) if isinstance(target_summary, dict) else None
        if _as_float(before) is None and _as_float(after) is None:
            continue
        metric_diffs.append(_diff_metric(key=key, before=before, after=after))

    metric_diffs.sort(key=lambda d: (-abs(float(d.get("delta") or 0.0)), str(d.get("key") or "")))
    return metric_diffs


def _slice_bucket_map(obj: Any) -> tuple[dict[str, dict[str, Any]], bool]:
    if not isinstance(obj, dict):
        return {}, False
    truncated = bool(obj.get("truncated"))
    raw = obj.get("buckets")
    if not isinstance(raw, list):
        return {}, truncated
    out: dict[str, dict[str, Any]] = {}
    for item in raw:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or "").strip().lower()
        if key:
            out[key] = item
    return out, truncated


def _coerce_bucket_items(value: Any) -> int:
    try:
        return int(value or 0)
    except Exception:
        return 0


def _build_slice_metric_diffs(*, before_obj: dict[str, Any], after_obj: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        _diff_metric(key=metric_key, before=before_obj.get(metric_key), after=after_obj.get(metric_key))
        for metric_key in _RETRIEVAL_DIFF_KEYS
    ]


def _build_slice_rows(
    *,
    base_map: dict[str, dict[str, Any]],
    target_map: dict[str, dict[str, Any]],
    max_slice_buckets: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for bucket_key in sorted(set(base_map) | set(target_map)):
        before_obj = base_map.get(bucket_key) or {}
        after_obj = target_map.get(bucket_key) or {}
        rows.append(
            {
                "key": bucket_key,
                "items_before": _coerce_bucket_items(before_obj.get("items")),
                "items_after": _coerce_bucket_items(after_obj.get("items")),
                "metrics": _build_slice_metric_diffs(before_obj=before_obj, after_obj=after_obj),
            }
        )

    rows.sort(
        key=lambda row: (
            -max(int(row.get("items_before") or 0), int(row.get("items_after") or 0)),
            str(row.get("key") or ""),
        )
    )
    if max_slice_buckets > 0 and len(rows) > max_slice_buckets:
        return rows[:max_slice_buckets]
    return rows


def _build_slice_diffs(
    *,
    base_summary: dict[str, Any],
    target_summary: dict[str, Any],
    max_slice_buckets: int,
) -> dict[str, Any]:
    base_slices = _coerce_slices(base_summary)
    target_slices = _coerce_slices(target_summary)
    slice_diffs: dict[str, Any] = {}

    for dim in _SLICE_DIFF_DIMS:
        base_map, base_trunc = _slice_bucket_map(base_slices.get(dim))
        target_map, target_trunc = _slice_bucket_map(target_slices.get(dim))
        slice_diffs[dim] = {
            "truncated_before": bool(base_trunc),
            "truncated_after": bool(target_trunc),
            "buckets": _build_slice_rows(
                base_map=base_map,
                target_map=target_map,
                max_slice_buckets=max_slice_buckets,
            ),
        }

    return slice_diffs


def diff_regression_run_summaries(
    *,
    base_run_id: UUID,
    target_run_id: UUID,
    base_summary: dict[str, Any],
    target_summary: dict[str, Any],
    max_slice_buckets: int = 40,
) -> dict[str, Any]:
    """
    Compute a stable diff payload between two regression run summaries.

    Input summaries are raw JSONB blobs (best-effort).
    """
    max_slice_buckets = max(0, min(int(max_slice_buckets or 0), 200))
    metric_diffs = _build_metric_diffs(base_summary=base_summary, target_summary=target_summary)
    diff_score = _build_diff_score(base_summary=base_summary, target_summary=target_summary)
    slice_diffs = _build_slice_diffs(
        base_summary=base_summary,
        target_summary=target_summary,
        max_slice_buckets=max_slice_buckets,
    )

    return {
        "base_run_id": str(base_run_id),
        "target_run_id": str(target_run_id),
        "generated_at": _now_utc().isoformat(),
        "metric_diffs": metric_diffs,
        "diff_score": diff_score,
        "slice_diffs": slice_diffs,
    }


__all__ = ["diff_regression_run_summaries"]

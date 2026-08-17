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

    # ---- Top-level metric diffs (numeric/bool only) ----
    ignore_keys = {"retrieval_slices"}
    keys: set[str] = set()
    for src in (base_summary, target_summary):
        if not isinstance(src, dict):
            continue
        for k in src.keys():
            if k in ignore_keys:
                continue
            keys.add(str(k))

    metric_diffs: list[dict[str, Any]] = []
    for k in sorted(keys):
        before = base_summary.get(k) if isinstance(base_summary, dict) else None
        after = target_summary.get(k) if isinstance(target_summary, dict) else None
        if _as_float(before) is None and _as_float(after) is None:
            continue
        metric_diffs.append(_diff_metric(key=k, before=before, after=after))

    metric_diffs.sort(key=lambda d: (-abs(float(d.get("delta") or 0.0)), str(d.get("key") or "")))

    diff_score = _build_diff_score(base_summary=base_summary, target_summary=target_summary)

    # ---- Slice diffs ----
    base_slices = _coerce_slices(base_summary)
    target_slices = _coerce_slices(target_summary)

    def _slice_bucket_map(obj: Any) -> tuple[dict[str, dict[str, Any]], bool]:
        if not isinstance(obj, dict):
            return {}, False
        truncated = bool(obj.get("truncated"))
        raw = obj.get("buckets")
        if not isinstance(raw, list):
            return {}, truncated
        out: dict[str, dict[str, Any]] = {}
        for it in raw:
            if not isinstance(it, dict):
                continue
            key = str(it.get("key") or "").strip().lower()
            if not key:
                continue
            out[key] = it
        return out, truncated

    slice_diffs: dict[str, Any] = {}
    for dim in (
        "file_type",
        "language",
        "directory",
        # v3 slice taxonomy additions (stable + actionable):
        "access_mode",
        "hit_type",
        "quality",
        "pipeline_hash",
    ):
        base_map, base_trunc = _slice_bucket_map(base_slices.get(dim))
        target_map, target_trunc = _slice_bucket_map(target_slices.get(dim))
        bucket_keys = sorted(set(base_map.keys()) | set(target_map.keys()))

        rows: list[dict[str, Any]] = []
        for bkey in bucket_keys:
            before_obj = base_map.get(bkey) or {}
            after_obj = target_map.get(bkey) or {}
            try:
                items_before = int(before_obj.get("items") or 0)
            except Exception:
                items_before = 0
            try:
                items_after = int(after_obj.get("items") or 0)
            except Exception:
                items_after = 0

            diffs = []
            for mk in _RETRIEVAL_DIFF_KEYS:
                diffs.append(_diff_metric(key=mk, before=before_obj.get(mk), after=after_obj.get(mk)))

            rows.append(
                {
                    "key": bkey,
                    "items_before": int(items_before),
                    "items_after": int(items_after),
                    "metrics": diffs,
                }
            )

        # Sort by bucket size, then key.
        rows.sort(
            key=lambda r: (
                -max(int(r.get("items_before") or 0), int(r.get("items_after") or 0)),
                str(r.get("key") or ""),
            )
        )
        if max_slice_buckets > 0 and len(rows) > max_slice_buckets:
            rows = rows[:max_slice_buckets]

        slice_diffs[dim] = {
            "truncated_before": bool(base_trunc),
            "truncated_after": bool(target_trunc),
            "buckets": rows,
        }

    return {
        "base_run_id": str(base_run_id),
        "target_run_id": str(target_run_id),
        "generated_at": _now_utc().isoformat(),
        "metric_diffs": metric_diffs,
        "diff_score": diff_score,
        "slice_diffs": slice_diffs,
    }


__all__ = ["diff_regression_run_summaries"]

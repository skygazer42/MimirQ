"""
Helpers for "multi-parser competition" selection.

This module stays pure so it can be unit-tested without running parsers.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


def _grade_rank(value: Any) -> int:
    v = str(value or "").strip().lower()
    if v == "pass":
        return 2
    if v == "warn":
        return 1
    if v == "fail":
        return 0
    return 0


def _coerce_float(value: Any) -> float:
    try:
        if value is None:
            return 0.0
        if isinstance(value, bool):
            return 0.0
        f = float(value)
        if f != f:  # NaN
            return 0.0
        return f
    except Exception:
        return 0.0


def _coerce_int(value: Any) -> int:
    try:
        if value is None:
            return 0
        if isinstance(value, bool):
            return 0
        return int(value)
    except Exception:
        return 0


def _clamp01(value: Any) -> float:
    f = _coerce_float(value)
    if f <= 0.0:
        return 0.0
    if f >= 1.0:
        return 1.0
    return float(f)


def _normalize_weights(weights: Mapping[str, Any] | None) -> dict[str, float] | None:
    if weights is None:
        return None
    if not isinstance(weights, Mapping):
        return None
    out: dict[str, float] = {}
    for k in ("text", "table", "image", "reading_order"):
        if k not in weights:
            continue
        w = _coerce_float(weights.get(k))
        if w <= 0.0:
            continue
        out[k] = float(w)
    if not out:
        return None
    total = float(sum(out.values()))
    if total <= 0.0:
        return None
    # Normalize for stability (weights don't have to sum to 1 in config).
    return {k: float(v) / total for k, v in out.items()}


def compute_competition_matrix_score(attempt: Mapping[str, Any], *, weights: Mapping[str, Any]) -> float:
    """
    Compute a weighted score in [0..1] from attempt metrics:
      text_score / table_score / image_score / reading_order_score
    """
    w = _normalize_weights(weights) or {}
    if not w:
        return 0.0

    score = 0.0
    score += float(w.get("text", 0.0)) * _clamp01(attempt.get("text_score"))
    score += float(w.get("table", 0.0)) * _clamp01(attempt.get("table_score"))
    score += float(w.get("image", 0.0)) * _clamp01(attempt.get("image_score"))
    score += float(w.get("reading_order", 0.0)) * _clamp01(attempt.get("reading_order_score"))
    return max(0.0, min(1.0, float(score)))


def select_best_parse_attempt(
    attempts: Sequence[Mapping[str, Any]],
    *,
    weights: Mapping[str, Any] | None = None,
) -> Mapping[str, Any]:
    """
    Select the "best" parse attempt.

    Priority:
    1) grade: pass > warn > fail
    2) (optional) competition matrix score: higher is better
    3) parse_score: higher is better
    4) content_chars: higher is better

    Notes:
    - The matrix score is only used when `weights` is provided.
    - This function remains pure and does not import global settings.
    """
    items = list(attempts or [])
    if not items:
        raise ValueError("attempts_empty")

    normalized_weights = _normalize_weights(weights)

    def key(it: Mapping[str, Any]) -> tuple[int, float, float, int]:
        matrix_score = compute_competition_matrix_score(it, weights=normalized_weights) if normalized_weights else 0.0
        return (
            _grade_rank(it.get("grade")),
            float(matrix_score),
            _coerce_float(it.get("parse_score")),
            _coerce_int(it.get("content_chars")),
        )

    return max(items, key=key)


__all__ = [
    "compute_competition_matrix_score",
    "select_best_parse_attempt",
]

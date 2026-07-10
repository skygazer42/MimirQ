"""
Helpers for "multi-parser competition" selection.

This module stays pure so it can be unit-tested without running parsers.
"""


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
        if f != f:
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


def _component_score(item: Mapping[str, Any], key: str) -> float:
    if key == "text":
        return _coerce_float(item.get("text_score") if item.get("text_score") is not None else item.get("parse_score"))

    direct = item.get(f"{key}_score")
    if direct is not None:
        return _coerce_float(direct)

    components = item.get("quality_components")
    if isinstance(components, Mapping):
        return _coerce_float(components.get(key))

    return 0.0


def _normalize_weights(weights: Mapping[str, Any] | None) -> dict[str, float] | None:
    if weights is None or not isinstance(weights, Mapping):
        return None
    out: dict[str, float] = {}
    for key in ("text", "table", "image", "reading_order"):
        if key not in weights:
            continue
        weight = _coerce_float(weights.get(key))
        if weight <= 0.0:
            continue
        out[key] = float(weight)
    if not out:
        return None
    total = float(sum(out.values()))
    if total <= 0.0:
        return None
    return {key: float(value) / total for key, value in out.items()}


def compute_competition_matrix_score(attempt: Mapping[str, Any], *, weights: Mapping[str, Any]) -> float:
    """
    Compute a normalized weighted score in [0..1].

    The matrix uses the richer per-component metrics when available, but still
    falls back to existing `parse_score` / `quality_components` fields so the
    older competition callers keep working unchanged.
    """
    normalized_weights = _normalize_weights(weights) or {}
    if not normalized_weights:
        return 0.0

    score = 0.0
    for key in ("text", "table", "image", "reading_order"):
        score += float(normalized_weights.get(key, 0.0)) * _clamp01(_component_score(attempt, key))
    return max(0.0, min(1.0, float(score)))


def _weighted_quality_score(item: Mapping[str, Any], weights: Mapping[str, Any] | None) -> float:
    normalized_weights = _normalize_weights(weights)
    if not normalized_weights:
        return _coerce_float(item.get("parse_score"))
    return compute_competition_matrix_score(item, weights=normalized_weights)


def select_best_parse_attempt(
    attempts: Sequence[Mapping[str, Any]],
    *,
    weights: Mapping[str, Any] | None = None,
) -> Mapping[str, Any]:
    """
    Select the "best" parse attempt.

    Priority:
    1) grade: pass > warn > fail
    2) weighted quality score: higher is better
    3) parse_score: higher is better
    4) content_chars: higher is better
    """
    items = list(attempts or [])
    if not items:
        raise ValueError("attempts_empty")

    def key(it: Mapping[str, Any]) -> tuple[int, float, float, int]:
        return (
            _grade_rank(it.get("grade")),
            _weighted_quality_score(it, weights),
            _coerce_float(it.get("parse_score")),
            _coerce_int(it.get("content_chars")),
        )

    return max(items, key=key)


__all__ = [
    "compute_competition_matrix_score",
    "select_best_parse_attempt",
]

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


def _component_score(item: Mapping[str, Any], key: str) -> float:
    if key == "text":
        return _coerce_float(item.get("parse_score"))

    direct = item.get(f"{key}_score")
    if direct is not None:
        return _coerce_float(direct)

    components = item.get("quality_components")
    if isinstance(components, Mapping):
        return _coerce_float(components.get(key))

    return 0.0


def _weighted_quality_score(item: Mapping[str, Any], weights: Mapping[str, Any] | None) -> float:
    if not isinstance(weights, Mapping) or not weights:
        return _coerce_float(item.get("parse_score"))

    total = 0.0
    total_weight = 0.0
    for key in ("text", "table", "image", "reading_order"):
        weight = _coerce_float(weights.get(key))
        if weight <= 0.0:
            continue
        total += float(weight) * _component_score(item, key)
        total_weight += float(weight)
    if total_weight <= 0.0:
        return _coerce_float(item.get("parse_score"))
    return total / total_weight


def select_best_parse_attempt(
    attempts: Sequence[Mapping[str, Any]],
    *,
    weights: Mapping[str, Any] | None = None,
) -> Mapping[str, Any]:
    """
    Select the "best" parse attempt.

    Priority:
    1) grade: pass > warn > fail
    2) parse_score: higher is better
    3) content_chars: higher is better
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
    "select_best_parse_attempt",
]

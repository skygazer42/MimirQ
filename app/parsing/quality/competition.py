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


def select_best_parse_attempt(attempts: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
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

    def key(it: Mapping[str, Any]) -> tuple[int, float, int]:
        return (
            _grade_rank(it.get("grade")),
            _coerce_float(it.get("parse_score")),
            _coerce_int(it.get("content_chars")),
        )

    return max(items, key=key)


__all__ = [
    "select_best_parse_attempt",
]


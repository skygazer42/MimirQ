"""Shared optional scalar coercion for raw parsing metadata."""

from typing import Any


def coerce_int(value: Any) -> int | None:
    try:
        if value is None or isinstance(value, bool):
            return None
        return int(value)
    except Exception:
        return None


def coerce_float(value: Any) -> float | None:
    try:
        if value is None or isinstance(value, bool):
            return None
        number = float(value)
        if number != number:
            return None
        return number
    except Exception:
        return None


__all__ = ["coerce_float", "coerce_int"]

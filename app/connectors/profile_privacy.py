"""
DB catalog profiling privacy guards.

The catalog profiling output is intended to be digest-only. In particular we must
avoid persisting raw values (sample rows / top values lists) that could leak
sensitive information.
"""

from collections.abc import Mapping
from typing import Any

_ALWAYS_DROP_KEYS: set[str] = {
    "sample_values",
    "sample_rows",
    "samples",
    "top_values",
    "top_value",
    "raw_rows",
}


def _parse_row_count(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return None


def sanitize_db_profile_snapshot(profile: Mapping[str, Any] | None, *, min_rows: int = 50) -> dict[str, Any]:
    """
    Sanitize a profile payload before storage.

    Rules (conservative, safe-by-default):
    - Always drop known raw-value carriers (samples/top values lists).
    - For small tables (row_count_estimate < min_rows): keep only row_count_estimate.
    - For larger tables: keep only primitive fields (no nested dict/list) after drops.
    """
    raw = dict(profile) if profile is not None else {}
    row_count = _parse_row_count(raw.get("row_count_estimate"))

    if row_count is not None:
        raw["row_count_estimate"] = row_count
        if row_count < min_rows:
            return {"row_count_estimate": row_count}
    else:
        raw.pop("row_count_estimate", None)

    out: dict[str, Any] = {}
    for key, value in raw.items():
        if key in _ALWAYS_DROP_KEYS:
            continue
        if isinstance(value, (list, dict)):
            continue
        out[key] = value

    return out

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


def _coerce_int(value: Any) -> int | None:
    try:
        if value is None:
            return None
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
    raw = dict(profile or {})
    row_count = _coerce_int(raw.get("row_count_estimate"))
    min_rows_i = _coerce_int(min_rows) or 0

    if row_count is not None:
        raw["row_count_estimate"] = row_count
        if row_count < min_rows_i:
            return {"row_count_estimate": row_count}
    else:
        raw.pop("row_count_estimate", None)

    out: dict[str, Any] = {}
    for k, v in raw.items():
        key = str(k)
        if key in _ALWAYS_DROP_KEYS:
            continue
        if isinstance(v, (list, dict)):
            continue
        out[key] = v

    if row_count is not None:
        out["row_count_estimate"] = row_count
    return out

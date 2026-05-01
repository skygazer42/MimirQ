"""Ablation batch helpers for RAGAS regression runs."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

_DISALLOWED_GRID_KEYS = {"dataset_id", "case_ids", "metrics", "grid", "max_combinations"}


def _is_grid_value(value: Any) -> bool:
    return value is None or isinstance(value, (str, int, float, bool, dict))


def expand_ablation_grid(
    grid: Mapping[str, Sequence[Any]],
    *,
    max_combinations: int = 50,
    allowed_keys: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Expand a bounded cartesian grid into stable variant dictionaries."""
    max_combinations = max(1, int(max_combinations or 1))
    if not isinstance(grid, Mapping) or not grid:
        raise ValueError("grid must be a non-empty object")

    variants: list[dict[str, Any]] = [{}]
    for raw_key, raw_values in grid.items():
        key = str(raw_key or "").strip()
        if not key:
            raise ValueError("grid keys must be non-empty")
        if key in _DISALLOWED_GRID_KEYS:
            raise ValueError(f"grid key is not allowed: {key}")
        if allowed_keys is not None and key not in allowed_keys:
            raise ValueError(f"grid key is not supported: {key}")
        if isinstance(raw_values, (str, bytes)) or not isinstance(raw_values, Sequence):
            raise ValueError(f"grid[{key}] must be an array")

        values = list(raw_values)
        if not values:
            raise ValueError(f"grid[{key}] must not be empty")
        if any(not _is_grid_value(value) for value in values):
            raise ValueError(f"grid[{key}] contains unsupported values")

        next_variants: list[dict[str, Any]] = []
        for variant in variants:
            for value in values:
                next_variants.append({**variant, key: value})
                if len(next_variants) > max_combinations:
                    raise ValueError(f"ablation grid exceeds max_combinations={max_combinations}")
        variants = next_variants

    return variants


__all__ = ["expand_ablation_grid"]

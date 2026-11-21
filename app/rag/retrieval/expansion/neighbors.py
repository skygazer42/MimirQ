from collections.abc import Callable
from typing import Any


def expand_neighbors_by_score(
    *,
    ranked_items: list[dict[str, Any]],
    get_adjacent_ids: Callable[[str, int], list[str]],
    high_threshold: float = 0.7,
    mid_threshold: float = 0.4,
    high_span: int = 3,
    mid_span: int = 1,
) -> dict[str, Any]:
    expanded_ids: set[str] = set()
    expansion_map: dict[str, int] = {}
    for item in ranked_items:
        chunk_id = str(item["id"]).strip()
        if not chunk_id:
            continue
        expanded_ids.add(chunk_id)
        try:
            score = float(item.get("score") or 0.0)
        except (OverflowError, TypeError, ValueError):
            score = 0.0

        span = 0
        if score >= high_threshold:
            span = max(0, high_span)
        elif score >= mid_threshold:
            span = max(0, mid_span)
        if span <= 0:
            continue

        expansion_map[chunk_id] = span
        for adj in get_adjacent_ids(chunk_id, span):
            adj_id = adj.strip()
            if adj_id:
                expanded_ids.add(adj_id)

    return {
        "expanded_ids": expanded_ids,
        "expansion_map": expansion_map,
    }

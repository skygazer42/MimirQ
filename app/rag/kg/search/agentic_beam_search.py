from __future__ import annotations

from typing import Any


def run_agentic_beam_search(
    *,
    query: str,
    topic_entities: list[str],
    adjacency: dict[str, list[str]],
    beam_width: int = 3,
    max_depth: int = 3,
) -> dict[str, Any]:
    seeds = [str(item or "").strip() for item in list(topic_entities or []) if str(item or "").strip()]
    width = max(1, int(beam_width or 1))
    depth = max(1, int(max_depth or 1))

    paths: list[list[str]] = []
    for seed in seeds[:width]:
        frontier: list[list[str]] = [[seed]]
        best_path: list[str] | None = None
        for _ in range(depth):
            next_frontier: list[list[str]] = []
            for path in frontier:
                node = path[-1]
                for neighbor in list(adjacency.get(node) or [])[:width]:
                    candidate = path + [str(neighbor or "").strip()]
                    next_frontier.append(candidate)
                    best_path = candidate
            if not next_frontier:
                break
            frontier = next_frontier[:width]
        if best_path:
            paths.append(best_path)

    reason_codes = [] if paths else ["no_expandable_paths"]
    return {
        "schema": "mimirq.kg_agentic_beam_search.v1",
        "query": str(query or "").strip(),
        "seed_entities": seeds,
        "paths": paths,
        "reason_codes": reason_codes,
    }


__all__ = ["run_agentic_beam_search"]

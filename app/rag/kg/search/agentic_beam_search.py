from __future__ import annotations

import time
from typing import Any


def run_agentic_beam_search(
    *,
    query: str,
    topic_entities: list[str],
    adjacency: dict[str, list[str]],
    beam_width: int = 3,
    max_depth: int = 3,
    max_llm_calls: int | None = None,
    budget_seconds: float | None = None,
) -> dict[str, Any]:
    seeds = [str(item or "").strip() for item in topic_entities or [] if str(item or "").strip()]
    width = max(1, int(beam_width or 1))
    depth = max(1, int(max_depth or 1))
    max_calls = max(0, int(max_llm_calls or 0))
    budget_sec = max(0.0, float(budget_seconds or 0.0))
    started = time.perf_counter()
    calls_used = 0
    exhausted = False

    def _budget_exhausted() -> bool:
        if max_calls > 0 and calls_used >= max_calls:
            return True
        if budget_sec > 0.0 and (time.perf_counter() - started) >= budget_sec:
            return True
        return False

    paths: list[list[str]] = []
    for seed in seeds[:width]:
        if _budget_exhausted():
            exhausted = True
            break
        frontier: list[list[str]] = [[seed]]
        best_path: list[str] | None = None
        for _ in range(depth):
            if _budget_exhausted():
                exhausted = True
                break
            next_frontier: list[list[str]] = []
            for path in frontier:
                if _budget_exhausted():
                    exhausted = True
                    break
                node = path[-1]
                for neighbor in list(adjacency.get(node) or [])[:width]:
                    if _budget_exhausted():
                        exhausted = True
                        break
                    calls_used += 1
                    candidate = path + [str(neighbor or "").strip()]
                    next_frontier.append(candidate)
                    best_path = candidate
            if not next_frontier:
                break
            frontier = next_frontier[:width]
        if best_path:
            paths.append(best_path)

    reason_codes = [] if paths else ["no_expandable_paths"]
    if exhausted:
        if max_calls > 0 and calls_used >= max_calls:
            reason_codes.append("llm_call_budget_exhausted")
        elif budget_sec > 0.0:
            reason_codes.append("time_budget_exhausted")
    return {
        "schema": "mimirq.kg_agentic_beam_search.v1",
        "query": str(query or "").strip(),
        "seed_entities": seeds,
        "paths": paths,
        "reason_codes": reason_codes,
        "budget": {
            "max_llm_calls": max_calls or None,
            "budget_seconds": budget_sec or None,
            "llm_calls_used": int(calls_used),
            "elapsed_sec": round(float(time.perf_counter() - started), 6),
            "exhausted": bool(exhausted),
        },
    }


__all__ = ["run_agentic_beam_search"]

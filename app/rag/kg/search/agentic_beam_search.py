from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class _BeamBudget:
    max_calls: int
    budget_sec: float
    started: float = field(default_factory=time.perf_counter)
    calls_used: int = 0
    exhausted: bool = False

    def is_exhausted(self) -> bool:
        if self.max_calls > 0 and self.calls_used >= self.max_calls:
            return True
        if self.budget_sec > 0.0 and (time.perf_counter() - self.started) >= self.budget_sec:
            return True
        return False

    def consume_call(self) -> None:
        self.calls_used += 1

    def reason_codes(self, paths: list[list[str]]) -> list[str]:
        reason_codes = [] if paths else ["no_expandable_paths"]
        if not self.exhausted:
            return reason_codes
        if self.max_calls > 0 and self.calls_used >= self.max_calls:
            reason_codes.append("llm_call_budget_exhausted")
        elif self.budget_sec > 0.0:
            reason_codes.append("time_budget_exhausted")
        return reason_codes

    def as_dict(self) -> dict[str, Any]:
        return {
            "max_llm_calls": self.max_calls or None,
            "budget_seconds": self.budget_sec or None,
            "llm_calls_used": int(self.calls_used),
            "elapsed_sec": round(float(time.perf_counter() - self.started), 6),
            "exhausted": bool(self.exhausted),
        }


def _normalize_entities(topic_entities: list[str]) -> list[str]:
    return [str(item or "").strip() for item in topic_entities or [] if str(item or "").strip()]


def _neighbor_paths(
    path: list[str],
    *,
    adjacency: dict[str, list[str]],
    width: int,
    budget: _BeamBudget,
) -> list[list[str]]:
    next_paths: list[list[str]] = []
    for neighbor in list(adjacency.get(path[-1]) or [])[:width]:
        if budget.is_exhausted():
            budget.exhausted = True
            break
        budget.consume_call()
        next_paths.append(path + [str(neighbor or "").strip()])
    return next_paths


def _best_seed_path(
    seed: str,
    *,
    adjacency: dict[str, list[str]],
    width: int,
    depth: int,
    budget: _BeamBudget,
) -> list[str] | None:
    frontier: list[list[str]] = [[seed]]
    best_path: list[str] | None = None
    for _ in range(depth):
        if budget.is_exhausted():
            budget.exhausted = True
            break
        next_frontier: list[list[str]] = []
        for path in frontier:
            if budget.is_exhausted():
                budget.exhausted = True
                break
            candidates = _neighbor_paths(path, adjacency=adjacency, width=width, budget=budget)
            next_frontier.extend(candidates)
            if candidates:
                best_path = candidates[-1]
        if not next_frontier:
            break
        frontier = next_frontier[:width]
    return best_path


def _beam_paths(
    seeds: list[str],
    *,
    adjacency: dict[str, list[str]],
    width: int,
    depth: int,
    budget: _BeamBudget,
) -> list[list[str]]:
    paths: list[list[str]] = []
    for seed in seeds[:width]:
        if budget.is_exhausted():
            budget.exhausted = True
            break
        best_path = _best_seed_path(seed, adjacency=adjacency, width=width, depth=depth, budget=budget)
        if best_path:
            paths.append(best_path)
    return paths


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
    seeds = _normalize_entities(topic_entities)
    width = max(1, int(beam_width or 1))
    depth = max(1, int(max_depth or 1))
    budget = _BeamBudget(
        max_calls=max(0, int(max_llm_calls or 0)),
        budget_sec=max(0.0, float(budget_seconds or 0.0)),
    )
    paths = _beam_paths(seeds, adjacency=adjacency, width=width, depth=depth, budget=budget)
    return {
        "schema": "mimirq.kg_agentic_beam_search.v1",
        "query": str(query or "").strip(),
        "seed_entities": seeds,
        "paths": paths,
        "reason_codes": budget.reason_codes(paths),
        "budget": budget.as_dict(),
    }


__all__ = ["run_agentic_beam_search"]

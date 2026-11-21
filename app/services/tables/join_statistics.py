"""Build join diagnostics from the candidates already scored by the planner."""

from copy import deepcopy
from typing import Any


def build_join_statistics_snapshot(
    *,
    tables_total: int,
    pairwise: dict[str, Any],
    multi: dict[str, Any],
) -> dict[str, Any]:
    return deepcopy(
        {
            "schema": "mimirq.table_join_stats.v1",
            "tables_total": tables_total,
            "pairwise": {
                "candidates": pairwise["candidates"],
                "selected": pairwise["selected"],
                "ambiguous": pairwise["ambiguous"],
                "ambiguity_gap": pairwise["ambiguity_gap"],
            },
            "multi": {
                "candidates": multi["candidates"],
                "selected": multi["selected"],
                "ambiguous": multi["ambiguous"],
                "ambiguity_gap": multi["ambiguity_gap"],
                "states_explored": multi["states_explored"],
                "max_states": multi["max_states"],
            },
        }
    )


__all__ = ["build_join_statistics_snapshot"]

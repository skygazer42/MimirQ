from typing import Any

from app.services.table_schema_graph import (
    score_join_plan_candidates,
    score_multi_join_plan_candidates,
)


def build_join_statistics_snapshot(
    *,
    tables: list[dict[str, Any]],
    top_n: int = 3,
    ambiguity_score_gap: float = 0.03,
    max_states: int = 24,
) -> dict[str, Any]:
    normalized_tables: list[dict[str, Any]] = []
    for raw in tables or []:
        if not isinstance(raw, dict):
            continue
        tname = str(raw.get("table_name") or "").strip()
        cols = raw.get("columns")
        if not tname or not isinstance(cols, list):
            continue
        try:
            row_count = int(raw.get("row_count") or 0)
        except Exception:
            row_count = 0
        sample_rows_raw = raw.get("sample_rows")
        sample_rows = [r for r in sample_rows_raw if isinstance(r, dict)] if isinstance(sample_rows_raw, list) else []
        normalized_tables.append(
            {
                "table_name": tname,
                "table_aliases": [str(v) for v in (raw.get("table_aliases") or []) if str(v).strip()],
                "columns": [c for c in cols if isinstance(c, dict)],
                "row_count": max(0, row_count),
                "sample_rows": sample_rows[:50],
            }
        )

    pairwise = score_join_plan_candidates(
        tables=normalized_tables,
        top_n=max(1, int(top_n or 1)),
        ambiguity_score_gap=float(ambiguity_score_gap or 0.0),
    )
    multi = score_multi_join_plan_candidates(
        tables=normalized_tables,
        top_n=max(1, int(top_n or 1)),
        ambiguity_score_gap=float(ambiguity_score_gap or 0.0),
        max_states=max(4, int(max_states or 4)),
    )

    return {
        "schema": "mimirq.table_join_stats.v1",
        "tables_total": len(normalized_tables),
        "pairwise": {
            "candidates": list(pairwise["candidates"]),
            "selected": pairwise["selected"],
            "ambiguous": pairwise["ambiguous"],
            "ambiguity_gap": pairwise["ambiguity_gap"],
        },
        "multi": {
            "candidates": list(multi["candidates"]),
            "selected": multi["selected"],
            "ambiguous": multi["ambiguous"],
            "ambiguity_gap": multi["ambiguity_gap"],
            "states_explored": multi["states_explored"],
            "max_states": multi["max_states"],
        },
    }


__all__ = ["build_join_statistics_snapshot"]

from __future__ import annotations

from app.services.table_join_stats import build_join_statistics_snapshot


def test_build_join_statistics_snapshot_returns_pairwise_and_multi_candidates() -> None:
    out = build_join_statistics_snapshot(
        tables=[
            {
                "table_name": "sheet_0",
                "table_aliases": ["orders"],
                "row_count": 1000,
                "columns": [{"name": "user_id", "dtype": "int"}, {"name": "amount", "dtype": "float"}],
                "sample_rows": [{"user_id": 1, "amount": 10.0}],
            },
            {
                "table_name": "sheet_1",
                "table_aliases": ["users"],
                "row_count": 100,
                "columns": [{"name": "id", "dtype": "int"}, {"name": "region", "dtype": "text"}],
                "sample_rows": [{"id": 1, "region": "APAC"}],
            },
            {
                "table_name": "sheet_2",
                "table_aliases": ["profiles"],
                "row_count": 100,
                "columns": [{"name": "user_id", "dtype": "int"}, {"name": "tier", "dtype": "text"}],
                "sample_rows": [{"user_id": 1, "tier": "gold"}],
            },
        ],
        top_n=3,
        ambiguity_score_gap=0.03,
        max_states=16,
    )

    assert out["schema"] == "mimirq.table_join_stats.v1"
    assert int(out["tables_total"]) == 3
    pairwise = out.get("pairwise") or {}
    multi = out.get("multi") or {}
    assert isinstance(pairwise.get("candidates"), list)
    assert isinstance(multi.get("candidates"), list)
    assert int(multi.get("max_states") or 0) >= 4

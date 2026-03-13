from __future__ import annotations

import pytest


def test_build_table_schema_graph_builds_nodes_and_edges() -> None:
    from app.services.table_schema_graph import build_table_schema_graph

    graph = build_table_schema_graph(
        tables=[
            {
                "table_name": "sheet_0",
                "table_aliases": ["orders"],
                "columns": [{"name": "user_id", "dtype": "int"}, {"name": "amount", "dtype": "float"}],
            },
            {
                "table_name": "sheet_1",
                "table_aliases": ["users"],
                "columns": [{"name": "id", "dtype": "int"}, {"name": "region", "dtype": "text"}],
            },
        ]
    )

    assert list(graph.get("nodes") or []) == ["sheet_0", "sheet_1"]
    edges = list(graph.get("edges") or [])
    assert len(edges) == 1
    e0 = edges[0]
    assert str(e0.get("left_table") or "") == "sheet_0"
    assert str(e0.get("right_table") or "") == "sheet_1"
    assert float(e0.get("confidence") or 0.0) > 0.0


def test_score_join_plan_candidates_returns_deterministic_topn() -> None:
    from app.services.table_schema_graph import score_join_plan_candidates

    out = score_join_plan_candidates(
        tables=[
            {
                "table_name": "sheet_0",
                "table_aliases": ["orders"],
                "columns": [{"name": "user_id", "dtype": "int"}, {"name": "amount", "dtype": "float"}],
            },
            {
                "table_name": "sheet_1",
                "table_aliases": ["users"],
                "columns": [{"name": "id", "dtype": "int"}, {"name": "region", "dtype": "text"}],
            },
            {
                "table_name": "sheet_2",
                "table_aliases": ["users_archive"],
                "columns": [{"name": "id", "dtype": "int"}, {"name": "region", "dtype": "text"}],
            },
        ],
        top_n=2,
        ambiguity_score_gap=0.03,
    )

    candidates = list(out.get("candidates") or [])
    assert len(candidates) == 2
    assert str(candidates[0].get("candidate_id") or "")
    assert float(candidates[0].get("score") or 0.0) >= float(candidates[1].get("score") or 0.0)


def test_score_join_plan_candidates_applies_cost_model_penalties(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import settings
    from app.services.table_schema_graph import score_join_plan_candidates

    monkeypatch.setattr(settings, "TABLE_TAG_COST_MODEL_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "TABLE_TAG_COST_FANOUT_RATIO_ALERT", 5.0, raising=False)
    monkeypatch.setattr(settings, "TABLE_TAG_COST_FANOUT_PENALTY_WEIGHT", 0.2, raising=False)
    monkeypatch.setattr(settings, "TABLE_TAG_COST_SELECTIVITY_MIN", 0.6, raising=False)
    monkeypatch.setattr(settings, "TABLE_TAG_COST_SELECTIVITY_PENALTY_WEIGHT", 0.2, raising=False)

    out = score_join_plan_candidates(
        tables=[
            {
                "table_name": "big_orders",
                "table_aliases": ["orders"],
                "row_count": 10_000,
                "columns": [{"name": "user_id", "dtype": "int"}, {"name": "amount", "dtype": "float"}],
                "sample_rows": [{"user_id": 1}, {"user_id": 1}, {"user_id": 2}, {"user_id": 2}],
            },
            {
                "table_name": "small_users",
                "table_aliases": ["users"],
                "row_count": 100,
                "columns": [{"name": "id", "dtype": "int"}, {"name": "region", "dtype": "text"}],
                "sample_rows": [{"id": 1}, {"id": 1}, {"id": 1}, {"id": 2}],
            },
        ],
        top_n=1,
        ambiguity_score_gap=0.01,
    )

    candidates = list(out.get("candidates") or [])
    assert len(candidates) == 1
    c0 = candidates[0]
    assert float(c0.get("cost_penalty_score") or 0.0) > 0.0
    penalties = list(c0.get("penalties") or [])
    assert "high_join_fanout" in penalties
    assert "low_join_selectivity" in penalties

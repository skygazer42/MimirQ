from __future__ import annotations


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

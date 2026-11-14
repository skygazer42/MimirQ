def test_zero_fanout_weight_disables_penalty(monkeypatch):
    from app.services import table_schema_graph as graph

    monkeypatch.setattr(graph.settings, "TABLE_TAG_COST_MODEL_ENABLED", True)
    monkeypatch.setattr(graph.settings, "TABLE_TAG_COST_FANOUT_PENALTY_WEIGHT", 0.0)
    penalties, total, _ = graph._cost_model_penalties(
        left_row_count=1,
        right_row_count=1000,
        left_sample_rows=None,
        right_sample_rows=None,
        left_column="id",
        right_column="id",
    )
    assert penalties == []
    assert total == 0.0

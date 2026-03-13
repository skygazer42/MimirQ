from __future__ import annotations

import pytest


def _ambiguous_tables() -> list[dict]:
    return [
        {
            "table_name": "sheet_0",
            "table_aliases": ["orders"],
            "columns": [{"name": "user_id", "dtype": "int"}, {"name": "amount", "dtype": "float"}],
            "sample_rows": [{"user_id": 1, "amount": 100.0}],
        },
        {
            "table_name": "sheet_1",
            "table_aliases": ["users"],
            "columns": [{"name": "id", "dtype": "int"}, {"name": "region", "dtype": "text"}],
            "sample_rows": [{"id": 1, "region": "APAC"}],
        },
        {
            "table_name": "sheet_2",
            "table_aliases": ["users_archive"],
            "columns": [{"name": "id", "dtype": "int"}, {"name": "region", "dtype": "text"}],
            "sample_rows": [{"id": 1, "region": "APAC"}],
        },
    ]


def test_plan_join_query_raises_on_ambiguous_candidates_when_strict(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import settings
    from app.services.table_tag_service import plan_join_query_for_tables

    monkeypatch.setattr(settings, "TABLE_TAG_AMBIGUITY_STRICT_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "TABLE_TAG_AMBIGUITY_SCORE_GAP", 1.0, raising=False)
    monkeypatch.setattr(settings, "TABLE_TAG_PLAN_CANDIDATES_TOP_N", 3, raising=False)

    with pytest.raises(ValueError, match="ambiguous_join_plan"):
        plan_join_query_for_tables(
            question="按 region 统计订单金额前10",
            tables=_ambiguous_tables(),
            max_rows=10,
        )


def test_plan_join_query_keeps_candidates_when_not_strict(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import settings
    from app.services.table_tag_service import plan_join_query_for_tables

    monkeypatch.setattr(settings, "TABLE_TAG_AMBIGUITY_STRICT_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "TABLE_TAG_AMBIGUITY_SCORE_GAP", 1.0, raising=False)
    monkeypatch.setattr(settings, "TABLE_TAG_PLAN_CANDIDATES_TOP_N", 3, raising=False)

    out = plan_join_query_for_tables(
        question="按 region 统计订单金额前10",
        tables=_ambiguous_tables(),
        max_rows=10,
    )

    planner = out.get("planner") or {}
    assert planner.get("strategy") == "deterministic_join"
    assert planner.get("ambiguous") is True
    candidates = planner.get("candidates") or []
    assert isinstance(candidates, list)
    assert len(candidates) >= 2

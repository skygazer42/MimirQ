from __future__ import annotations


def test_score_schema_link_diagnostics_matches_columns_values_and_tables() -> None:
    from app.services.table_tag_service import score_schema_link_diagnostics

    diag = score_schema_link_diagnostics(
        question="统计 Sales 里 region=US 的 amount 总和",
        sql_table="sheet_0",
        columns=[{"name": "amount", "dtype": "int"}, {"name": "region", "dtype": "text"}],
        sample_rows=[{"region": "US", "amount": 10}, {"region": "EU", "amount": 20}],
        table_aliases=["sales.xlsx", "Sales"],
    )

    assert float(diag.get("score") or 0.0) > 0.0
    assert "amount" in list(diag.get("matched_columns") or [])
    assert "region" in list(diag.get("matched_columns") or [])
    assert "US" in list(diag.get("matched_values") or [])
    assert any(str(x).lower() == "sales" for x in list(diag.get("matched_tables") or []))
    assert str(diag.get("strategy") or "")
    assert str(diag.get("reason") or "")


def test_score_schema_link_diagnostics_returns_none_strategy_when_no_overlap() -> None:
    from app.services.table_tag_service import score_schema_link_diagnostics

    diag = score_schema_link_diagnostics(
        question="请写一首诗",
        sql_table="sheet_0",
        columns=[{"name": "amount", "dtype": "int"}],
        sample_rows=[],
        table_aliases=["sales.xlsx"],
    )

    assert float(diag.get("score") or 0.0) == 0.0
    assert list(diag.get("matched_columns") or []) == []
    assert list(diag.get("matched_values") or []) == []
    assert list(diag.get("matched_tables") or []) == []
    assert str(diag.get("strategy") or "") == "none"


def test_plan_join_query_for_tables_emits_bounded_join_sql() -> None:
    from app.services.table_tag_service import plan_join_query_for_tables

    plan = plan_join_query_for_tables(
        question="按 region 统计订单金额前10",
        tables=[
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
        ],
        max_rows=10,
    )

    sql = str(plan.get("sql") or "")
    assert "JOIN" in sql.upper()
    assert "LIMIT 10" in sql.upper()
    planner = plan.get("planner") or {}
    assert str(planner.get("strategy") or "") == "deterministic_join"
    joins = list(planner.get("joins") or [])
    assert len(joins) == 1

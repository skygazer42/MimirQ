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

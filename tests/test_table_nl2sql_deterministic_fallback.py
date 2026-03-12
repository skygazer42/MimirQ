from __future__ import annotations


def test_generate_sql_for_table_uses_deterministic_fallback_without_llm_key(monkeypatch) -> None:  # noqa: ANN001
    from app.core.config import settings
    from app.services.table_tag_service import generate_sql_for_table_with_mode

    monkeypatch.setattr(settings, "LLM_API_KEY", "", raising=False)
    monkeypatch.setattr(settings, "TABLE_NL2SQL_DETERMINISTIC_FALLBACK_ENABLED", True, raising=False)

    sql, mode = generate_sql_for_table_with_mode(
        question="总数有多少",
        sql_table="sheet_0",
        columns=[{"name": "amount", "dtype": "int"}],
        max_rows=20,
    )

    assert mode == "deterministic"
    assert "count" in sql.lower()
    assert '"sheet_0"' in sql


def test_generate_sql_for_table_with_mode_reports_llm_when_available(monkeypatch) -> None:  # noqa: ANN001
    import app.services.table_tag_service as mod
    from app.core.config import settings

    monkeypatch.setattr(settings, "LLM_API_KEY", "sk-test", raising=False)
    monkeypatch.setattr(settings, "TABLE_NL2SQL_DETERMINISTIC_FALLBACK_ENABLED", True, raising=False)

    class _Resp:
        content = 'SELECT "amount" FROM "sheet_0" LIMIT 5'

    class _FakeLLM:
        def invoke(self, _msgs):  # noqa: ANN001
            return _Resp()

    monkeypatch.setattr(mod, "_build_llm", lambda **_k: _FakeLLM(), raising=True)

    sql, mode = mod.generate_sql_for_table_with_mode(
        question="查 amount",
        sql_table="sheet_0",
        columns=[{"name": "amount", "dtype": "int"}],
        max_rows=20,
    )

    assert mode == "llm"
    assert "select" in sql.lower()


def test_generate_sql_for_table_with_metadata_exposes_schema_link_and_planner_diagnostics(monkeypatch) -> None:  # noqa: ANN001
    from app.core.config import settings
    from app.services.table_tag_service import generate_sql_for_table_with_metadata

    monkeypatch.setattr(settings, "LLM_API_KEY", "", raising=False)
    monkeypatch.setattr(settings, "TABLE_NL2SQL_DETERMINISTIC_FALLBACK_ENABLED", True, raising=False)

    sql, mode, metadata = generate_sql_for_table_with_metadata(
        question="按 region 分组统计 amount 总和，按总和降序前 3 条",
        sql_table="sheet_0",
        columns=[{"name": "amount", "dtype": "int"}, {"name": "region", "dtype": "text"}],
        max_rows=20,
        sample_rows=[{"region": "US", "amount": 10}, {"region": "EU", "amount": 20}],
        table_aliases=["sales.xlsx", "Sales"],
    )

    assert mode == "deterministic"
    assert 'SUM("amount")' in sql
    assert 'GROUP BY "region"' in sql
    assert "ORDER BY total DESC" in sql
    assert "LIMIT 3" in sql

    schema_link = metadata.get("schema_link") or {}
    assert isinstance(schema_link, dict)
    assert float(schema_link.get("score") or 0.0) > 0.0
    assert "amount" in list(schema_link.get("matched_columns") or [])
    assert "region" in list(schema_link.get("matched_columns") or [])
    assert str(schema_link.get("strategy") or "")

    planner = metadata.get("planner") or {}
    assert planner.get("aggregation") == "sum"
    assert planner.get("group_by") == "region"
    assert (planner.get("order_by") or {}).get("column") == "total"
    assert (planner.get("order_by") or {}).get("direction") == "desc"


def test_generate_sql_for_table_with_metadata_supports_filter_hint(monkeypatch) -> None:  # noqa: ANN001
    from app.core.config import settings
    from app.services.table_tag_service import generate_sql_for_table_with_metadata

    monkeypatch.setattr(settings, "LLM_API_KEY", "", raising=False)
    monkeypatch.setattr(settings, "TABLE_NL2SQL_DETERMINISTIC_FALLBACK_ENABLED", True, raising=False)

    sql, mode, metadata = generate_sql_for_table_with_metadata(
        question="筛选 region 为 US 的 amount 前 5 条",
        sql_table="sheet_0",
        columns=[{"name": "amount", "dtype": "int"}, {"name": "region", "dtype": "text"}],
        max_rows=50,
        sample_rows=[{"region": "US", "amount": 10}],
    )

    assert mode == "deterministic"
    assert 'WHERE "region" = \'US\'' in sql
    assert "LIMIT 5" in sql
    planner = metadata.get("planner") or {}
    filt = planner.get("filter") or {}
    assert filt.get("column") == "region"
    assert filt.get("value") == "US"

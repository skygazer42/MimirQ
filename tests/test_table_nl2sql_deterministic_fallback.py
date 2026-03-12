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


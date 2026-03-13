from __future__ import annotations

import pytest


def test_generate_sql_with_metadata_emits_stable_sql_fingerprint(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import settings
    from app.services.table_tag_service import generate_sql_for_table_with_metadata

    monkeypatch.setattr(settings, "TABLE_NL2SQL_DETERMINISTIC_ONLY", True, raising=False)
    monkeypatch.setattr(settings, "LLM_API_KEY", "", raising=False)

    sql_a, mode_a, meta_a = generate_sql_for_table_with_metadata(
        question="统计 amount 总和",
        sql_table="sheet_0",
        columns=[{"name": "amount", "dtype": "float"}],
        max_rows=20,
        sample_rows=[{"amount": 100.0}],
        table_aliases=["orders"],
    )
    sql_b, mode_b, meta_b = generate_sql_for_table_with_metadata(
        question="统计 amount 总和",
        sql_table="sheet_0",
        columns=[{"name": "amount", "dtype": "float"}],
        max_rows=20,
        sample_rows=[{"amount": 100.0}],
        table_aliases=["orders"],
    )

    assert mode_a == "deterministic"
    assert mode_b == "deterministic"
    assert sql_a == sql_b
    fp_a = str(meta_a.get("sql_fingerprint") or "")
    fp_b = str(meta_b.get("sql_fingerprint") or "")
    assert fp_a
    assert fp_a == fp_b
    assert str((meta_a.get("planner") or {}).get("sql_fingerprint") or "") == fp_a


def test_join_planner_emits_sql_fingerprint(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import settings
    from app.services.table_tag_service import plan_join_query_for_tables

    monkeypatch.setattr(settings, "TABLE_TAG_AMBIGUITY_STRICT_ENABLED", False, raising=False)

    out = plan_join_query_for_tables(
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

    planner = out.get("planner") or {}
    fp = str(planner.get("sql_fingerprint") or "")
    assert fp
    assert len(fp) >= 8

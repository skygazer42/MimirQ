from __future__ import annotations

from scripts.remote_table_store_probe import validate_table_store_probe


def test_remote_table_store_probe_accepts_consistent_table_payloads() -> None:
    table_list_body = {
        "items": [
            {
                "table_id": "doc:1:sheet:0",
                "row_count": 2,
                "col_count": 3,
            }
        ]
    }
    table_detail_body = {
        "columns": [
            {"name": "region", "dtype": "string"},
            {"name": "amount", "dtype": "Int64"},
            {"name": "status", "dtype": "string"},
        ],
        "sample_rows": [
            {"region": "APAC", "amount": 1200, "status": "review"},
            {"region": "EMEA", "amount": 800, "status": "done"},
        ],
    }
    table_preview_body = {
        "columns": ["region", "amount", "status"],
        "rows": [
            ["APAC", 1200, "review"],
            ["EMEA", 800, "done"],
        ],
    }
    table_query_body = {
        "columns": ["region", "amount", "status"],
        "rows": [
            ["APAC", 1200, "review"],
            ["EMEA", 800, "done"],
        ],
    }

    failures = validate_table_store_probe(
        table_list_body=table_list_body,
        table_detail_body=table_detail_body,
        table_preview_body=table_preview_body,
        table_query_body=table_query_body,
    )

    assert failures == []


def test_remote_table_store_probe_flags_missing_rows_or_columns() -> None:
    failures = validate_table_store_probe(
        table_list_body={"items": [{"table_id": "doc:1:sheet:0", "row_count": 0, "col_count": 0}]},
        table_detail_body={"columns": [], "sample_rows": []},
        table_preview_body={"columns": ["region"], "rows": []},
        table_query_body={"columns": ["region"], "rows": []},
    )

    assert any("row_count" in item for item in failures)
    assert any("col_count" in item for item in failures)
    assert any("table_detail.columns" in item for item in failures)
    assert any("table_detail.sample_rows" in item for item in failures)
    assert any("preview.columns" in item for item in failures)
    assert any("query.columns" in item for item in failures)

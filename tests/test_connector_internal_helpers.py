from __future__ import annotations

import base64

from tests.test_confluence_connector_unit import _import_connectors_with_lightweight_stubs


def test_schedule_interval_seconds_supports_supported_formats() -> None:
    connectors = _import_connectors_with_lightweight_stubs()

    assert connectors._schedule_interval_seconds("@hourly") == 60 * 60
    assert connectors._schedule_interval_seconds("@daily") == 60 * 60 * 24
    assert connectors._schedule_interval_seconds("*/15 * * * *") == 15 * 60
    assert connectors._schedule_interval_seconds("0 */6 * * *") == 6 * 60 * 60
    assert connectors._schedule_interval_seconds("0 0 */2 * *") == 2 * 24 * 60 * 60
    assert connectors._schedule_interval_seconds("bad-cron") is None


def test_connector_error_code_from_message_prefers_keywords_and_status() -> None:
    connectors = _import_connectors_with_lightweight_stubs()

    assert (
        connectors._connector_error_code_from_message(
            "request blocked by private ip policy",
            default="http_403",
            status_code=403,
        )
        == "ssrf"
    )
    assert (
        connectors._connector_error_code_from_message(
            "gateway timeout while crawling",
            default="http_504",
            status_code=504,
        )
        == "timeout"
    )
    assert (
        connectors._connector_error_code_from_message(
            "payload too large",
            default="http_413",
            status_code=413,
        )
        == "too_large"
    )
    assert (
        connectors._connector_error_code_from_message(
            "validation failed",
            default="http_400",
            status_code=400,
        )
        == "bad_request"
    )
    assert (
        connectors._connector_error_code_from_message(
            "mystery backend error",
            default="http_500",
            status_code=500,
        )
        == "http_500"
    )


def test_append_unique_limited_preserves_uniqueness_and_limit() -> None:
    connectors = _import_connectors_with_lightweight_stubs()

    items = ["a", "b"]
    connectors._append_unique_limited(items, "b", limit=3)
    connectors._append_unique_limited(items, "c", limit=3)
    connectors._append_unique_limited(items, "d", limit=3)

    assert items == ["a", "b", "c"]


def test_build_basic_auth_header_requires_both_credentials() -> None:
    connectors = _import_connectors_with_lightweight_stubs()

    expected = base64.b64encode(b"bot@example.com:secret").decode("ascii")
    assert connectors._build_basic_auth_header("bot@example.com", "secret") == {
        "Authorization": f"Basic {expected}"
    }
    assert connectors._build_basic_auth_header("bot@example.com", "") == {}


def test_build_retry_failed_run_config_supports_url_batch_and_web_crawl() -> None:
    connectors = _import_connectors_with_lightweight_stubs()

    connector_id, cfg = connectors._build_retry_failed_run_config(
        connector_id="url_batch",
        base_cfg={"urls": ["https://example.com/a"], "parser_backend": "auto"},
        failed_urls=["https://example.com/b"],
    )
    assert connector_id == "url_batch"
    assert cfg == {"urls": ["https://example.com/b"], "parser_backend": "auto"}

    connector_id, cfg = connectors._build_retry_failed_run_config(
        connector_id="web_crawl",
        base_cfg={
            "start_urls": ["https://example.com/docs"],
            "filename": "crawl.json",
            "user_agent": "bot",
            "auth": {"type": "bearer", "token": "x"},
            "parser_backend": "auto",
            "chunk_strategy": "langchain_recursive",
            "pipeline": {"ocr": True},
            "access": {"mode": "inherit"},
            "max_pages": 10,
        },
        failed_urls=["https://example.com/a", "https://example.com/b"],
    )
    assert connector_id == "url_batch"
    assert cfg == {
        "urls": ["https://example.com/a", "https://example.com/b"],
        "filename": "crawl.json",
        "user_agent": "bot",
        "auth": {"type": "bearer", "token": "x"},
        "parser_backend": "auto",
        "chunk_strategy": "langchain_recursive",
        "pipeline": {"ocr": True},
        "access": {"mode": "inherit"},
    }


def test_connector_run_has_abortable_task_requires_queue_and_string_task_id() -> None:
    connectors = _import_connectors_with_lightweight_stubs()

    assert connectors._connector_run_has_abortable_task(task_queue_enabled=False, task_id="job-1") is False
    assert connectors._connector_run_has_abortable_task(task_queue_enabled=True, task_id=None) is False
    assert connectors._connector_run_has_abortable_task(task_queue_enabled=True, task_id=123) is False
    assert connectors._connector_run_has_abortable_task(task_queue_enabled=True, task_id="job-1") is True


def test_db_catalog_row_sync_settings_uses_connector_flags_and_defaults() -> None:
    connectors = _import_connectors_with_lightweight_stubs()

    connectors.settings.DB_CATALOG_ROW_SYNC_ENABLED = True
    connectors.settings.DB_CATALOG_ROW_SYNC_MAX_TABLES = 20
    connectors.settings.DB_CATALOG_ROW_SYNC_MAX_ROWS_PER_TABLE = 50
    connectors.settings.DB_CATALOG_ROW_SYNC_MAX_COLS = 40

    enabled, max_tables, max_rows, max_cols = connectors._db_catalog_row_sync_settings(
        {
            "row_sync_enabled": True,
            "row_sync_max_tables": 8,
        }
    )

    assert enabled is True
    assert max_tables == 8
    assert max_rows == 50
    assert max_cols == 40


def test_db_catalog_schema_diff_counts_extracts_nested_counts() -> None:
    connectors = _import_connectors_with_lightweight_stubs()

    diff_counts = connectors._db_catalog_schema_diff_counts(
        {
            "tables_added": {"count": 2},
            "tables_removed": {"count": 1},
            "columns_added": {"count": 4},
            "columns_removed": {"count": 3},
            "columns_changed": {"count": 5},
        }
    )

    assert diff_counts == {
        "tables_added": 2,
        "tables_removed": 1,
        "columns_added": 4,
        "columns_removed": 3,
        "columns_changed": 5,
    }

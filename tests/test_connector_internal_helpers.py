from __future__ import annotations

import base64
import types

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


def test_build_web_crawl_execution_plan_resumes_full_sync_from_saved_cursor() -> None:
    connectors = _import_connectors_with_lightweight_stubs()

    plan = connectors._build_web_crawl_execution_plan(
        run_stats={},
        state={"cursor": 2},
        crawl_urls=[
            "https://example.com/docs/a",
            "https://example.com/docs/b",
            "https://example.com/docs/c",
            "https://example.com/docs/d",
        ],
        crawl_sync_tokens={},
    )

    assert plan["mode"] == "full"
    assert plan["crawl_urls"] == [
        "https://example.com/docs/c",
        "https://example.com/docs/d",
    ]
    assert plan["cursor_in"] == 2
    assert plan["processed_visible"] == 2
    assert plan["resumed_from_state"] is True
    assert plan["delta_urls"] == [
        "https://example.com/docs/a",
        "https://example.com/docs/b",
        "https://example.com/docs/c",
        "https://example.com/docs/d",
    ]
    assert plan["removed_urls"] == []
    assert plan["source_manifest_state"] == {}


def test_build_web_crawl_execution_plan_tracks_changed_and_removed_urls() -> None:
    connectors = _import_connectors_with_lightweight_stubs()

    plan = connectors._build_web_crawl_execution_plan(
        run_stats={},
        state={
            "source_manifest": {
                "https://example.com/docs/a": "content_type:text/html|body_sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                "https://example.com/docs/obsolete": "content_type:text/html|body_sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
            }
        },
        crawl_urls=[
            "https://example.com/docs/a",
            "https://example.com/docs/c",
        ],
        crawl_sync_tokens={
            "https://example.com/docs/a": "content_type:text/html|body_sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
            "https://example.com/docs/c": "content_type:text/html|body_sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd",
        },
    )

    assert plan["mode"] == "incremental"
    assert plan["delta_urls"] == [
        "https://example.com/docs/a",
        "https://example.com/docs/c",
    ]
    assert plan["skipped_unchanged"] == 0
    assert plan["removed_urls"] == ["https://example.com/docs/obsolete"]
    assert plan["source_manifest_state"] == {
        "https://example.com/docs/a": "content_type:text/html|body_sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
    }


def test_build_url_batch_run_state_uses_run_documents_when_stats_lack_document_ids() -> None:
    connectors = _import_connectors_with_lightweight_stubs()

    run = types.SimpleNamespace(
        stats={"cursor": 1, "processed_urls": 1},
        documents=[
            types.SimpleNamespace(source_ref="https://example.com/1", document_id="doc-1"),
            types.SimpleNamespace(source_ref="", document_id=""),
        ],
    )

    state = connectors._build_url_batch_run_state(
        run=run,
        urls=["https://example.com/1", "https://example.com/2"],
    )

    assert state["processed_refs"] == {"https://example.com/1"}
    assert state["cursor"] == 1
    assert state["start_idx"] == 1
    assert state["created_doc_ids"] == ["doc-1"]
    assert state["created"] == 0
    assert state["failed"] == 0
    assert state["stats"]["total_urls"] == 2
    assert state["stats"]["document_ids"] == ["doc-1"]


def test_build_url_batch_run_state_clamps_cursor_and_preserves_existing_document_ids() -> None:
    connectors = _import_connectors_with_lightweight_stubs()

    run = types.SimpleNamespace(
        stats={
            "cursor": 99,
            "processed_urls": 3,
            "created": "bad-value",
            "failed": "2",
            "document_ids": ["doc-9", "doc-10"],
        },
        documents=[types.SimpleNamespace(source_ref="https://example.com/1", document_id="doc-1")],
    )

    state = connectors._build_url_batch_run_state(
        run=run,
        urls=["https://example.com/1", "https://example.com/2"],
    )

    assert state["cursor"] == 99
    assert state["start_idx"] == 2
    assert state["created_doc_ids"] == ["doc-9", "doc-10"]
    assert state["created"] == 2
    assert state["failed"] == 2

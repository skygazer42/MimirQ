from __future__ import annotations

import base64
import types
from datetime import datetime, timezone

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


def test_build_github_repo_execution_plan_resumes_full_sync_from_saved_cursor() -> None:
    connectors = _import_connectors_with_lightweight_stubs()

    plan = connectors._build_github_repo_execution_plan(
        run_stats={},
        state={"cursor": 1},
        tree_items=[
            {"type": "blob", "path": "a.md", "sha": "sha-a"},
            {"type": "blob", "path": "b.md", "sha": "sha-b"},
            {"type": "blob", "path": "c.txt", "sha": "sha-c"},
        ],
        include_set={".md", ".txt"},
        max_files=4,
        enable_source_acl=False,
    )

    assert plan["mode"] == "full"
    assert plan["files"] == [
        ("a.md", "sha-a"),
        ("b.md", "sha-b"),
        ("c.txt", "sha-c"),
    ]
    assert plan["delta_files"] == [
        ("a.md", "sha-a"),
        ("b.md", "sha-b"),
        ("c.txt", "sha-c"),
    ]
    assert plan["files_to_process"] == [
        ("b.md", "sha-b"),
        ("c.txt", "sha-c"),
    ]
    assert plan["cursor_in"] == 1
    assert plan["processed_visible"] == 1
    assert plan["resumed_from_state"] is True
    assert plan["removed_paths"] == []


def test_build_github_repo_execution_plan_preserves_tracked_paths_seen_outside_processing_window() -> None:
    connectors = _import_connectors_with_lightweight_stubs()

    plan = connectors._build_github_repo_execution_plan(
        run_stats={},
        state={"source_manifest": {"legacy.txt": "sha-legacy", "z.md": "sha-z"}},
        tree_items=[
            {"type": "blob", "path": "legacy.txt", "sha": "sha-legacy"},
            {"type": "blob", "path": "a.md", "sha": "sha-a"},
            {"type": "blob", "path": "z.md", "sha": "sha-z"},
        ],
        include_set={".md"},
        max_files=1,
        enable_source_acl=False,
    )

    assert plan["mode"] == "incremental"
    assert plan["files"] == [("a.md", "sha-a")]
    assert plan["delta_files"] == [("a.md", "sha-a")]
    assert plan["removed_paths"] == []
    assert plan["source_manifest_state"] == {
        "legacy.txt": "sha-legacy",
        "z.md": "sha-z",
    }


def test_build_drive_files_execution_plan_resumes_full_sync_from_saved_cursor() -> None:
    connectors = _import_connectors_with_lightweight_stubs()

    plan = connectors._build_drive_files_execution_plan(
        run_stats={},
        state={"cursor": 1},
        discovered_sources=[
            ("drive://file-1", "file-1", "file-1", "token-1"),
            ("drive://file-2", "file-2", "file-2", "token-2"),
            ("drive://file-3", "file-3", "file-3", "token-3"),
        ],
        enable_source_acl=False,
    )

    assert plan["mode"] == "full"
    assert plan["delta_sources"] == [
        ("drive://file-1", "file-1", "file-1", "token-1"),
        ("drive://file-2", "file-2", "file-2", "token-2"),
        ("drive://file-3", "file-3", "file-3", "token-3"),
    ]
    assert plan["sources_to_process"] == [
        ("drive://file-2", "file-2", "file-2", "token-2"),
        ("drive://file-3", "file-3", "file-3", "token-3"),
    ]
    assert plan["cursor_in"] == 1
    assert plan["processed_visible"] == 1
    assert plan["resumed_from_state"] is True
    assert plan["removed_source_refs"] == []


def test_build_drive_files_execution_plan_tracks_removed_sources_and_manifest_state() -> None:
    connectors = _import_connectors_with_lightweight_stubs()

    plan = connectors._build_drive_files_execution_plan(
        run_stats={},
        state={"source_manifest": {"file-a": "token-a", "file-obsolete": "token-obsolete"}},
        discovered_sources=[
            ("drive://file-a", "file-a", "file-a", "token-a"),
            ("drive://file-b", "file-b", "file-b", "token-b"),
        ],
        enable_source_acl=False,
    )

    assert plan["mode"] == "incremental"
    assert plan["delta_sources"] == [
        ("drive://file-b", "file-b", "file-b", "token-b"),
    ]
    assert plan["skipped_unchanged"] == 1
    assert plan["removed_source_refs"] == ["file-obsolete"]
    assert plan["source_manifest_state"] == {"file-a": "token-a"}


def test_build_drive_files_execution_plan_keeps_unchanged_sources_when_acl_inheritance_enabled() -> None:
    connectors = _import_connectors_with_lightweight_stubs()

    plan = connectors._build_drive_files_execution_plan(
        run_stats={},
        state={"source_manifest": {"file-a": "token-a"}},
        discovered_sources=[
            ("drive://file-a", "file-a", "file-a", "token-a"),
        ],
        enable_source_acl=True,
    )

    assert plan["mode"] == "incremental"
    assert plan["delta_sources"] == [
        ("drive://file-a", "file-a", "file-a", "token-a"),
    ]
    assert plan["skipped_unchanged"] == 0


def test_minio_object_token_includes_etag_timestamp_and_size() -> None:
    connectors = _import_connectors_with_lightweight_stubs()

    token = connectors._minio_object_token(
        types.SimpleNamespace(
            etag="etag-1",
            last_modified=datetime(2026, 3, 10, 12, 34, 56, tzinfo=timezone.utc),
            size=123,
        )
    )

    assert token == "etag:etag-1|last_modified:2026-03-10T12:34:56Z|size:123"


def test_build_minio_bucket_execution_plan_resumes_full_sync_from_saved_cursor() -> None:
    connectors = _import_connectors_with_lightweight_stubs()

    scope_hash = connectors._minio_source_scope_hash(bucket_name="docs", prefix="", include_set={".md"})
    plan = connectors._build_minio_bucket_execution_plan(
        run_stats={},
        state={"cursor": 1},
        listed_objects=[
            {"name": "a.md", "token": "token-a"},
            {"name": "b.md", "token": "token-b"},
            {"name": "c.md", "token": "token-c"},
        ],
        include_set={".md"},
        max_objects=10,
        scope_hash=scope_hash,
    )

    assert plan["mode"] == "full"
    assert plan["delta_objects_total"] == 3
    assert plan["objects_to_process"] == [
        ("b.md", "token-b"),
        ("c.md", "token-c"),
    ]
    assert plan["cursor_in"] == 1
    assert plan["processed_visible"] == 1
    assert plan["resumed_from_state"] is True
    assert plan["removed_paths"] == []


def test_build_minio_bucket_execution_plan_resets_manifest_on_scope_hash_change() -> None:
    connectors = _import_connectors_with_lightweight_stubs()

    old_scope_hash = "old-scope"
    new_scope_hash = connectors._minio_source_scope_hash(bucket_name="docs", prefix="fresh", include_set={".md"})
    plan = connectors._build_minio_bucket_execution_plan(
        run_stats={},
        state={
            "cursor": 2,
            "source_manifest": {"a.md": "token-a", "obsolete.md": "token-obsolete"},
            "source_scope_hash": old_scope_hash,
        },
        listed_objects=[
            {"name": "a.md", "token": "token-a"},
            {"name": "b.md", "token": "token-b"},
        ],
        include_set={".md"},
        max_objects=10,
        scope_hash=new_scope_hash,
    )

    assert plan["mode"] == "full"
    assert plan["existing_manifest"] == {}
    assert plan["removed_paths"] == []
    assert plan["source_manifest_state"] == {}
    assert plan["objects_to_process"] == []


def test_build_confluence_space_run_settings_normalizes_config() -> None:
    connectors = _import_connectors_with_lightweight_stubs()

    settings_map = connectors._build_confluence_space_run_settings(
        {
            "base_url": "https://example.atlassian.net/wiki/ ",
            "space_key": " DOCS ",
            "sync_mode": "auto",
            "_state": {
                "last_modified": "2026-03-01T00:00:00.000Z",
                "last_modified_ids": ["123", "", None],
            },
            "max_pages": 999,
            "page_size": 0,
            "soft_delete": True,
            "ingest_method": "WEBUI",
            "user_agent": "ExampleAgent/1.0",
            "source_acl": {"mode": "inherit", "fallback_mode": "all_team_members"},
            "access": {"mode": "inherit"},
            "include_attachments": True,
            "max_attachments_per_page": 999,
            "max_total_attachments": 9999,
        }
    )

    assert settings_map["base_url"] == "https://example.atlassian.net/wiki"
    assert settings_map["space_key"] == "DOCS"
    assert settings_map["cursor_last_modified"] == "2026-03-01T00:00:00.000Z"
    assert settings_map["cursor_last_modified_ids"] == {"123"}
    assert settings_map["effective_mode"] == "incremental"
    assert settings_map["max_pages"] == 500
    assert settings_map["page_size"] == 25
    assert settings_map["soft_delete"] is True
    assert settings_map["ingest_method"] == "webui"
    assert settings_map["api_base"] == "https://example.atlassian.net/wiki/rest/api"
    assert settings_map["search_url"] == "https://example.atlassian.net/wiki/rest/api/content/search"
    assert settings_map["headers"]["Accept"] == "application/json"
    assert settings_map["headers"]["User-Agent"] == "ExampleAgent/1.0"
    assert settings_map["enable_source_acl"] is True
    assert settings_map["source_acl_fallback_mode"] == "all_team_members"
    assert settings_map["include_attachments"] is True
    assert settings_map["max_attachments_per_page"] == 50
    assert settings_map["max_total_attachments"] == 2000


def test_build_confluence_space_search_cql_adds_incremental_boundary() -> None:
    connectors = _import_connectors_with_lightweight_stubs()

    cql = connectors._build_confluence_space_search_cql(
        space_key="DOCS",
        effective_mode="incremental",
        cursor_last_modified="2026-03-01T00:00:00.000Z",
    )

    assert cql == (
        'space="DOCS" and type=page and status=current'
        ' and lastmodified >= "2026-03-01T00:00:00.000Z"'
        " ORDER BY lastmodified ASC"
    )


def test_initialize_confluence_space_run_stats_includes_cursor_and_attachment_limits() -> None:
    connectors = _import_connectors_with_lightweight_stubs()

    run = types.SimpleNamespace(stats={"keep": "me"})
    stats = connectors._initialize_confluence_space_run_stats(
        run=run,
        settings_map={
            "effective_mode": "incremental",
            "ingest_method": "api_view",
            "space_key": "DOCS",
            "base_url": "https://example.atlassian.net/wiki",
            "max_pages": 25,
            "page_size": 10,
            "include_attachments": True,
            "max_attachments_per_page": 5,
            "max_total_attachments": 50,
            "cursor_last_modified": "2026-03-01T00:00:00.000Z",
        },
    )

    assert stats["keep"] == "me"
    assert stats["mode"] == "incremental"
    assert stats["ingest_method"] == "api_view"
    assert stats["space_key"] == "DOCS"
    assert stats["base_url"] == "https://example.atlassian.net/wiki"
    assert stats["max_pages"] == 25
    assert stats["page_size"] == 10
    assert stats["include_attachments"] is True
    assert stats["max_attachments_per_page"] == 5
    assert stats["max_total_attachments"] == 50
    assert stats["cursor_in"] == "2026-03-01T00:00:00.000Z"
    assert stats["processed_pages"] == 0
    assert stats["created"] == 0
    assert stats["failed"] == 0
    assert stats["processed_attachments"] == 0
    assert stats["created_attachments"] == 0
    assert stats["failed_attachments"] == 0
    assert stats["skipped_attachments"] == 0
    assert stats["skipped_boundary_duplicates"] == 0
    assert stats["failed_urls"] == []
    assert stats["errors"] == []
    assert stats["error_groups"] == []

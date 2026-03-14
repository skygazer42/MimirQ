from __future__ import annotations

import asyncio
import base64
import types
import uuid
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


def test_schedule_interval_from_parts_supports_minute_hour_and_day_steps() -> None:
    connectors = _import_connectors_with_lightweight_stubs()

    assert connectors._schedule_interval_from_parts("*/15", "*", "*", "*", "*") == 15 * 60
    assert connectors._schedule_interval_from_parts("0", "*/6", "*", "*", "*") == 6 * 60 * 60
    assert connectors._schedule_interval_from_parts("0", "0", "*/2", "*", "*") == 2 * 24 * 60 * 60
    assert connectors._schedule_interval_from_parts("5", "*", "*", "*", "*") is None


def test_jira_mapping_text_prefers_display_fields_in_priority_order() -> None:
    connectors = _import_connectors_with_lightweight_stubs()

    assert connectors._jira_mapping_text({"displayName": "Ada", "name": "Ignored"}) == "Ada"
    assert connectors._jira_mapping_text({"name": "Priority", "value": "Ignored"}) == "Priority"
    assert connectors._jira_mapping_text({"value": 42}) == "42"
    assert connectors._jira_mapping_text({"summary": "Ticket summary"}) == "Ticket summary"
    assert connectors._jira_mapping_text({"displayName": ""}) == ""


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


def test_nested_diff_count_returns_zero_for_missing_or_invalid_entries() -> None:
    connectors = _import_connectors_with_lightweight_stubs()

    assert connectors._nested_diff_count({}, "tables_added") == 0
    assert connectors._nested_diff_count({"tables_added": {"count": "7"}}, "tables_added") == 7
    assert connectors._nested_diff_count({"tables_added": {"count": None}}, "tables_added") == 0
    assert connectors._nested_diff_count({"tables_added": []}, "tables_added") == 0


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


def test_url_batch_processed_refs_and_document_ids_ignore_blank_values() -> None:
    connectors = _import_connectors_with_lightweight_stubs()

    documents = [
        types.SimpleNamespace(source_ref="https://example.com/1", document_id="doc-1"),
        types.SimpleNamespace(source_ref=" ", document_id=" "),
        types.SimpleNamespace(source_ref="https://example.com/2", document_id="doc-2"),
    ]

    assert connectors._url_batch_processed_refs(documents) == {
        "https://example.com/1",
        "https://example.com/2",
    }
    assert connectors._url_batch_document_ids(stats={}, documents=documents) == ["doc-1", "doc-2"]
    assert connectors._url_batch_document_ids(stats={"document_ids": ["doc-9", "doc-10"]}, documents=documents) == [
        "doc-9",
        "doc-10",
    ]


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


def test_github_repo_path_is_included_supports_extension_and_extensionless_paths() -> None:
    connectors = _import_connectors_with_lightweight_stubs()

    assert connectors._github_repo_path_is_included("docs/readme.md", {".md"}) is True
    assert connectors._github_repo_path_is_included("docs/readme.txt", {".md"}) is False
    assert connectors._github_repo_path_is_included("LICENSE", {""}) is True
    assert connectors._github_repo_path_is_included("LICENSE", {".md"}) is False


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


def test_drive_permission_external_ids_and_anyone_skips_deleted_and_deduplicates_groups() -> None:
    connectors = _import_connectors_with_lightweight_stubs()

    ext_ids, has_anyone = connectors._drive_permission_external_ids_and_anyone(
        [
            {"type": "group", "emailAddress": "eng@example.com"},
            {"type": "group", "emailAddress": "eng@example.com"},
            {"type": "anyone"},
            {"type": "group", "emailAddress": "deleted@example.com", "deleted": True},
            {"type": "user", "emailAddress": "ada@example.com"},
            "not-a-dict",
        ]
    )

    assert ext_ids == ["drive:group:eng@example.com"]
    assert has_anyone is True


def test_process_drive_files_sources_only_passes_required_ingest_args(monkeypatch) -> None:  # noqa: ANN001
    connectors = _import_connectors_with_lightweight_stubs()

    created_id = uuid.uuid4()
    tenant_id = uuid.uuid4()
    run_id = uuid.uuid4()
    seen: dict[str, object] = {}

    monkeypatch.setattr(connectors, "_drive_files_run_cancelled", lambda *_a, **_k: False, raising=True)
    monkeypatch.setattr(connectors, "_append_connector_error", lambda stats, **_k: stats, raising=True)

    async def _fake_ingest_drive_file_source(  # noqa: ANN202
        _client,
        _db,
        *,
        run,
        run_id,
        tenant_id,
        requested_by,
        source_ref,
        file_id,
        settings_map,
    ):  # noqa: ANN001
        seen["ingest_run"] = run
        seen["ingest_run_id"] = run_id
        seen["ingest_tenant_id"] = tenant_id
        seen["ingest_requested_by"] = requested_by
        seen["ingest_source_ref"] = source_ref
        seen["ingest_file_id"] = file_id
        seen["ingest_settings_map"] = settings_map
        return {"doc_id": created_id, "updated_existing": 0}

    def _fake_persist_drive_files_progress(_db, **kwargs):  # noqa: ANN001
        seen["persist_kwargs"] = dict(kwargs)

    monkeypatch.setattr(
        connectors,
        "_ingest_drive_file_source",
        _fake_ingest_drive_file_source,
        raising=True,
    )
    monkeypatch.setattr(
        connectors,
        "_persist_drive_files_progress",
        _fake_persist_drive_files_progress,
        raising=True,
    )

    out = asyncio.run(
        connectors._process_drive_files_sources(
            object(),
            object(),
            run=types.SimpleNamespace(id=run_id, dataset_id=uuid.uuid4(), stats={}),
            run_id=run_id,
            tenant_id=tenant_id,
            requested_by="tester",
            settings_map={"enable_source_acl": False},
            discovered_sources=[("drive://file-1", "file-1", "file-1", "token-1")],
            plan={
                "sources_to_process": [("drive://file-1", "file-1", "file-1", "token-1")],
                "source_manifest_state": {},
                "cursor_in": 0,
            },
        )
    )

    assert out == {
        "created": 1,
        "failed": 0,
        "created_doc_ids": [created_id],
        "delta_acl_docs_updated": 0,
        "delta_acl_sources_updated": 0,
        "removed_paths_reconciled": 0,
        "removed_documents_disabled": 0,
        "source_manifest_state": {"file-1": "token-1"},
    }
    assert seen["ingest_run_id"] == run_id
    assert seen["ingest_tenant_id"] == tenant_id
    assert seen["ingest_requested_by"] == "tester"
    assert seen["ingest_source_ref"] == "file-1"
    assert seen["ingest_file_id"] == "file-1"
    assert seen["ingest_settings_map"] == {"enable_source_acl": False}
    assert seen["persist_kwargs"]["processed"] == 1
    assert seen["persist_kwargs"]["source_manifest_state"] == {"file-1": "token-1"}


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


def test_minio_object_name_is_included_supports_extension_and_extensionless_names() -> None:
    connectors = _import_connectors_with_lightweight_stubs()

    assert connectors._minio_object_name_is_included("notes.md", {".md"}) is True
    assert connectors._minio_object_name_is_included("notes.txt", {".md"}) is False
    assert connectors._minio_object_name_is_included("README", {""}) is True
    assert connectors._minio_object_name_is_included("README", {".md"}) is False


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


def test_normalize_connector_sync_mode_and_effective_mode() -> None:
    connectors = _import_connectors_with_lightweight_stubs()

    assert connectors._normalize_connector_sync_mode("FULL") == "full"
    assert connectors._normalize_connector_sync_mode("weird") == "auto"
    assert connectors._resolve_connector_effective_mode(sync_mode="auto", cursor_last_modified="2026-03-01T00:00:00.000Z") == (
        "incremental"
    )
    assert connectors._resolve_connector_effective_mode(sync_mode="auto", cursor_last_modified="") == "full"
    assert connectors._resolve_connector_effective_mode(sync_mode="incremental", cursor_last_modified="") == "full"


def test_confluence_source_acl_settings_disable_inherit_when_manual_access_override_exists() -> None:
    connectors = _import_connectors_with_lightweight_stubs()

    acl_settings = connectors._confluence_source_acl_settings(
        {
            "access": {"mode": "partial_members"},
            "source_acl": {"mode": "inherit", "fallback_mode": "all_team_members"},
        }
    )

    assert acl_settings == {
        "access": {"mode": "partial_members"},
        "source_acl_mode": "inherit",
        "source_acl_fallback_mode": "all_team_members",
        "has_manual_access_override": True,
        "enable_source_acl": False,
    }


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


def test_build_jira_project_run_settings_normalizes_config() -> None:
    connectors = _import_connectors_with_lightweight_stubs()

    settings_map = connectors._build_jira_project_run_settings(
        {
            "base_url": "https://example.atlassian.net/ ",
            "project_key": " plat ",
            "sync_mode": "auto",
            "_state": {
                "last_modified": "2026-03-01T12:34:56.000+0000",
                "last_modified_ids": ["10000", "", None],
            },
            "max_issues": 999,
            "page_size": 0,
            "include_comments": False,
            "max_comments_per_issue": 999,
            "custom_fields": ["customfield_10016", "customfield_10016", "bad_field", "customfield_10017"],
            "include_attachments": True,
            "max_attachments_per_issue": 999,
            "max_total_attachments": 9999,
            "include_linked_artifacts": True,
            "max_linked_artifacts_per_issue": 999,
            "max_total_linked_artifacts": 9999,
            "chunk_strategy": "jira_ticket",
            "user_agent": "ExampleJiraAgent/1.0",
            "source_acl": {"mode": "inherit", "fallback_mode": "all_team_members"},
            "access": {"mode": "inherit"},
            "jql": "labels = platform",
        }
    )

    assert settings_map["base_url"] == "https://example.atlassian.net"
    assert settings_map["project_key"] == "PLAT"
    assert settings_map["cursor_last_modified"] == "2026-03-01T12:34:56.000+0000"
    assert settings_map["cursor_last_modified_ids"] == {"10000"}
    assert settings_map["effective_mode"] == "incremental"
    assert settings_map["max_issues"] == 500
    assert settings_map["page_size"] == 25
    assert settings_map["include_comments"] is False
    assert settings_map["max_comments_per_issue"] == 200
    assert settings_map["custom_fields"] == ["customfield_10016", "customfield_10017"]
    assert settings_map["include_attachments"] is True
    assert settings_map["max_attachments_per_issue"] == 50
    assert settings_map["max_total_attachments"] == 2000
    assert settings_map["include_linked_artifacts"] is True
    assert settings_map["max_linked_artifacts_per_issue"] == 50
    assert settings_map["max_total_linked_artifacts"] == 2000
    assert settings_map["search_url"] == "https://example.atlassian.net/rest/api/3/search"
    assert settings_map["headers"]["Accept"] == "application/json"
    assert settings_map["headers"]["User-Agent"] == "ExampleJiraAgent/1.0"
    assert settings_map["enable_source_acl"] is True
    assert settings_map["source_acl_fallback_mode"] == "all_team_members"
    assert settings_map["extra_jql"] == "labels = platform"


def test_build_jira_project_search_jql_adds_extra_jql_and_incremental_boundary() -> None:
    connectors = _import_connectors_with_lightweight_stubs()
    connectors._jira_jql_updated_after = lambda _raw: "2026-03-01 12:34"  # type: ignore[method-assign]

    jql = connectors._build_jira_project_search_jql(
        project_key="PLAT",
        extra_jql="labels = platform",
        effective_mode="incremental",
        cursor_last_modified="2026-03-01T12:34:56.000+0000",
    )

    assert jql == (
        'project = "PLAT"'
        " AND (labels = platform)"
        ' AND updated >= "2026-03-01 12:34"'
        " ORDER BY updated ASC"
    )


def test_initialize_jira_project_run_stats_includes_cursor_and_related_limits() -> None:
    connectors = _import_connectors_with_lightweight_stubs()

    run = types.SimpleNamespace(stats={"keep": "me"})
    stats = connectors._initialize_jira_project_run_stats(
        run=run,
        settings_map={
            "effective_mode": "incremental",
            "project_key": "PLAT",
            "base_url": "https://example.atlassian.net",
            "max_issues": 25,
            "page_size": 10,
            "include_comments": True,
            "max_comments_per_issue": 5,
            "include_attachments": True,
            "max_attachments_per_issue": 3,
            "max_total_attachments": 30,
            "include_linked_artifacts": True,
            "max_linked_artifacts_per_issue": 2,
            "max_total_linked_artifacts": 20,
            "cursor_last_modified": "2026-03-01T12:34:56.000+0000",
        },
    )

    assert stats["keep"] == "me"
    assert stats["mode"] == "incremental"
    assert stats["project_key"] == "PLAT"
    assert stats["base_url"] == "https://example.atlassian.net"
    assert stats["max_issues"] == 25
    assert stats["page_size"] == 10
    assert stats["include_comments"] is True
    assert stats["max_comments_per_issue"] == 5
    assert stats["include_attachments"] is True
    assert stats["max_attachments_per_issue"] == 3
    assert stats["max_total_attachments"] == 30
    assert stats["include_linked_artifacts"] is True
    assert stats["max_linked_artifacts_per_issue"] == 2
    assert stats["max_total_linked_artifacts"] == 20
    assert stats["cursor_in"] == "2026-03-01T12:34:56.000+0000"
    assert stats["processed_issues"] == 0
    assert stats["processed_attachments"] == 0
    assert stats["processed_linked_artifacts"] == 0
    assert stats["created"] == 0
    assert stats["created_attachments"] == 0
    assert stats["created_linked_artifacts"] == 0
    assert stats["failed"] == 0
    assert stats["skipped_boundary_duplicates"] == 0
    assert stats["removed_issues_reconciled"] == 0
    assert stats["removed_documents_disabled"] == 0
    assert stats["removed_attachment_documents_disabled"] == 0
    assert stats["removed_linked_artifact_documents_disabled"] == 0
    assert stats["failed_urls"] == []
    assert stats["errors"] == []
    assert stats["error_groups"] == []


def test_build_jira_issue_info_extracts_issue_identity_and_updated_timestamp() -> None:
    connectors = _import_connectors_with_lightweight_stubs()

    out = connectors._build_jira_issue_info(
        base_url="https://example.atlassian.net",
        issue={
            "id": "10000",
            "key": "PLAT-42",
            "fields": {"updated": "2026-03-02T12:34:56.000+0000"},
        },
    )

    assert out == {
        "issue_id": "10000",
        "issue_key": "PLAT-42",
        "issue_url": "https://example.atlassian.net/browse/PLAT-42",
        "updated": "2026-03-02T12:34:56.000+0000",
    }


def test_resolve_jira_issue_acl_maps_groups_and_records_delta(monkeypatch) -> None:  # noqa: ANN001
    connectors = _import_connectors_with_lightweight_stubs()
    import app.services.document_acl_provenance_service as provenance_service

    tenant_id = uuid.uuid4()
    run_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    mapped_group_id = uuid.uuid4()
    seen: dict[str, object] = {}

    def _fake_resolve_groups(*_a, **kwargs):  # noqa: ANN001
        seen["external_ids"] = list(kwargs.get("external_ids") or [])
        return {mapped_group_id}

    monkeypatch.setattr(connectors, "_resolve_tenant_group_ids_by_external_id", _fake_resolve_groups, raising=True)

    def _fake_delta(*_a, **kwargs):  # noqa: ANN001
        seen["delta_kwargs"] = dict(kwargs)
        return 2

    monkeypatch.setattr(connectors, "_delta_sync_jira_documents_acl_by_issue_url", _fake_delta, raising=False)

    def _fake_provenance(**kwargs):  # noqa: ANN001
        seen["provenance_kwargs"] = dict(kwargs)
        return {"schema": "test-provenance", "restricted": kwargs.get("restricted")}

    monkeypatch.setattr(provenance_service, "build_document_acl_provenance", _fake_provenance, raising=True)

    effective_access, acl_provenance, updated_existing = connectors._resolve_jira_issue_acl(
        object(),
        tenant_id=tenant_id,
        run_id=run_id,
        requested_by="tester",
        run=types.SimpleNamespace(dataset_id=dataset_id),
        issue={
            "fields": {
                "security": {"id": "10001"},
                "comment": {"comments": [{"visibility": {"type": "role", "value": "Developers"}}]},
            }
        },
        issue_info={"issue_url": "https://example.atlassian.net/browse/PLAT-42"},
        settings_map={
            "access": None,
            "enable_source_acl": True,
            "include_comments": True,
            "max_comments_per_issue": 5,
            "source_acl_mode": "inherit",
            "source_acl_fallback_mode": "partial_members",
            "base_url": "https://example.atlassian.net",
            "project_key": "PLAT",
        },
    )

    assert effective_access == {
        "mode": "partial_members",
        "partial_group_list": [str(mapped_group_id)],
    }
    assert acl_provenance == {"schema": "test-provenance", "restricted": True}
    assert updated_existing == 2
    assert set(seen.get("external_ids") or []) == {
        "jira:policy:security-level/10001",
        "jira:role:developers",
    }
    assert (seen.get("delta_kwargs") or {}).get("issue_url") == "https://example.atlassian.net/browse/PLAT-42"
    assert (seen.get("provenance_kwargs") or {}).get("connector_id") == "jira_project"
    assert (seen.get("provenance_kwargs") or {}).get("connector_run_id") == str(run_id)


def test_persist_jira_project_progress_updates_stats_and_last_modified_ids() -> None:
    connectors = _import_connectors_with_lightweight_stubs()

    class _DummyDB:
        def __init__(self) -> None:
            self.commits = 0

        def commit(self) -> None:
            self.commits += 1

    dummy_db = _DummyDB()
    run = types.SimpleNamespace(stats={"keep": "me"})

    connectors._persist_jira_project_progress(
        dummy_db,
        run=run,
        progress={
            "processed": 3,
            "attachments_processed": 2,
            "linked_artifacts_processed": 1,
            "created": 5,
            "attachments_created": 2,
            "linked_artifacts_created": 1,
            "failed": 1,
            "skipped_boundary_duplicates": 1,
            "created_doc_ids": ["doc-1", "doc-2"],
            "delta_acl_docs_updated": 4,
            "delta_acl_sources_updated": 2,
            "removed_issues_reconciled": 1,
            "removed_documents_disabled": 3,
            "removed_attachment_documents_disabled": 1,
            "removed_linked_artifact_documents_disabled": 2,
            "last_modified_seen": "2026-03-02T12:34:56.000+0000",
            "last_modified_ids_seen": {"10000", "10001"},
        },
    )

    assert dummy_db.commits == 1
    assert run.stats["keep"] == "me"
    assert run.stats["processed_issues"] == 3
    assert run.stats["processed_attachments"] == 2
    assert run.stats["processed_linked_artifacts"] == 1
    assert run.stats["cursor"] == 3
    assert run.stats["created"] == 5
    assert run.stats["created_attachments"] == 2
    assert run.stats["created_linked_artifacts"] == 1
    assert run.stats["failed"] == 1
    assert run.stats["skipped_boundary_duplicates"] == 1
    assert run.stats["document_ids"] == ["doc-1", "doc-2"]
    assert run.stats["acl_delta_sync_updated_documents"] == 4
    assert run.stats["acl_delta_sync_updated_sources"] == 2
    assert run.stats["removed_issues_reconciled"] == 1
    assert run.stats["removed_documents_disabled"] == 3
    assert run.stats["removed_attachment_documents_disabled"] == 1
    assert run.stats["removed_linked_artifact_documents_disabled"] == 2
    assert run.stats["last_modified"] == "2026-03-02T12:34:56.000+0000"
    assert run.stats["last_modified_ids"] == ["10000", "10001"]


def test_ingest_single_jira_linked_artifact_sets_metadata_and_auth_headers(monkeypatch) -> None:  # noqa: ANN001
    connectors = _import_connectors_with_lightweight_stubs()

    run_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    doc_id = uuid.uuid4()
    seen: dict[str, object] = {}

    class _DummyDB:
        def __init__(self) -> None:
            self.added: list[object] = []
            self.commits = 0

        def add(self, obj: object) -> None:
            self.added.append(obj)

        def commit(self) -> None:
            self.commits += 1

    dummy_db = _DummyDB()

    async def _fake_ingest_url_upload_request(*_a, **kwargs):  # noqa: ANN001
        body = kwargs["body"]
        seen["body_url"] = getattr(body, "url", None)
        seen["body_fetch_headers"] = getattr(body, "fetch_headers", None)
        seen["body_filename"] = getattr(body, "filename", None)
        doc = types.SimpleNamespace(id=doc_id, doc_metadata={})
        seen["doc"] = doc
        return doc

    def _fake_apply_document_access_from_config(*_a, **kwargs):  # noqa: ANN001
        seen["effective_access"] = kwargs.get("access")

    def _fake_apply_connector_identity_metadata(**kwargs):  # noqa: ANN001
        seen["identity_source_ref"] = kwargs.get("source_ref")
        seen["identity_source_id"] = kwargs.get("source_id")

    class _DummyUrlUploadRequest:
        def __init__(self, **kwargs):  # noqa: ANN003
            for key, value in kwargs.items():
                setattr(self, key, value)

    monkeypatch.setattr(connectors, "UrlUploadRequest", _DummyUrlUploadRequest, raising=False)
    monkeypatch.setattr(connectors, "_ingest_url_upload_request", _fake_ingest_url_upload_request, raising=False)
    monkeypatch.setattr(
        connectors,
        "_apply_document_access_from_config",
        _fake_apply_document_access_from_config,
        raising=False,
    )
    monkeypatch.setattr(
        connectors,
        "_apply_connector_identity_metadata",
        _fake_apply_connector_identity_metadata,
        raising=False,
    )

    created_id = asyncio.run(
        connectors._ingest_single_jira_linked_artifact(
            dummy_db,
            run=types.SimpleNamespace(id=run_id, dataset_id=dataset_id),
            tenant_id=uuid.uuid4(),
            requested_by="tester",
            issue_info={
                "issue_id": "10000",
                "issue_key": "PLAT-42",
                "issue_url": "https://example.atlassian.net/browse/PLAT-42",
                "updated": "2026-03-02T12:34:56.000+0000",
            },
            link_url="https://example.atlassian.net/wiki/spaces/PLAT/pages/42",
            effective_access={"mode": "partial_members"},
            acl_provenance={"schema": "test-provenance"},
            settings_map={
                "base_url": "https://example.atlassian.net",
                "project_key": "PLAT",
                "auth_headers": {"Authorization": "Basic token"},
                "user_agent": "MimirQ-Jira/1.0",
                "parser_backend": "auto",
                "chunk_strategy": "langchain_recursive",
                "pipeline": {"ocr": True},
                "effective_mode": "incremental",
            },
        )
    )

    assert created_id == doc_id
    assert seen["body_url"] == "https://example.atlassian.net/wiki/spaces/PLAT/pages/42"
    assert seen["body_fetch_headers"] == {"Authorization": "Basic token"}
    assert seen["body_filename"] is None
    assert seen["effective_access"] == {"mode": "partial_members"}
    assert seen["identity_source_ref"] == "https://example.atlassian.net/wiki/spaces/PLAT/pages/42"
    assert seen["identity_source_id"] == "https://example.atlassian.net/wiki/spaces/PLAT/pages/42"
    assert dummy_db.commits == 1
    assert len(dummy_db.added) == 1

    doc = seen["doc"]
    assert doc.doc_metadata["acl_provenance"] == {"schema": "test-provenance"}
    assert doc.doc_metadata["source_last_modified_source"] == connectors.JIRA_UPDATED_SOURCE
    assert doc.doc_metadata["connector"]["doc_kind"] == "linked_artifact"
    assert doc.doc_metadata["connector"]["issue_key"] == "PLAT-42"
    assert doc.doc_metadata["connector"]["link_url"] == "https://example.atlassian.net/wiki/spaces/PLAT/pages/42"


def test_ingest_jira_issue_linked_artifacts_tracks_created_docs_and_reconciles(monkeypatch) -> None:  # noqa: ANN001
    connectors = _import_connectors_with_lightweight_stubs()

    created_ids = [uuid.uuid4(), uuid.uuid4()]
    seen: dict[str, object] = {}

    monkeypatch.setattr(
        connectors,
        "_jira_extract_linked_artifact_urls",
        lambda *_a, **_k: [
            "https://example.atlassian.net/wiki/spaces/PLAT/pages/42",
            "https://docs.example.com/design-spec",
        ],
        raising=True,
    )
    monkeypatch.setattr(connectors, "_jira_project_run_cancelled", lambda *_a, **_k: False, raising=False)

    async def _fake_ingest_single_jira_linked_artifact(*_a, **kwargs):  # noqa: ANN001
        link_url = str(kwargs.get("link_url") or "")
        seen.setdefault("link_urls", []).append(link_url)
        return created_ids[len(seen["link_urls"]) - 1]

    def _fake_soft_disable(*_a, **kwargs):  # noqa: ANN001
        seen["seen_link_urls"] = set(kwargs.get("seen_link_urls") or set())
        return 4

    monkeypatch.setattr(
        connectors,
        "_ingest_single_jira_linked_artifact",
        _fake_ingest_single_jira_linked_artifact,
        raising=False,
    )
    monkeypatch.setattr(
        connectors,
        "_soft_disable_jira_linked_artifact_documents_missing_from_issue",
        _fake_soft_disable,
        raising=True,
    )

    out = asyncio.run(
        connectors._ingest_jira_issue_linked_artifacts(
            object(),
            run=types.SimpleNamespace(id=uuid.uuid4(), dataset_id=uuid.uuid4(), status="running", stats={}),
            tenant_id=uuid.uuid4(),
            requested_by="tester",
            issue={"fields": {"description": "irrelevant"}},
            issue_info={
                "issue_id": "10000",
                "issue_key": "PLAT-42",
                "issue_url": "https://example.atlassian.net/browse/PLAT-42",
                "updated": "2026-03-02T12:34:56.000+0000",
            },
            effective_access={"mode": "inherit"},
            acl_provenance={"schema": "test-provenance"},
            settings_map={
                "base_url": "https://example.atlassian.net",
                "project_key": "PLAT",
                "include_linked_artifacts": True,
                "max_total_linked_artifacts": 5,
                "max_linked_artifacts_per_issue": 2,
                "include_comments": True,
                "max_comments_per_issue": 5,
                "auth_headers": {"Authorization": "Basic token"},
                "user_agent": "MimirQ-Jira/1.0",
                "parser_backend": "auto",
                "chunk_strategy": "langchain_recursive",
                "pipeline": {"ocr": True},
                "effective_mode": "full",
            },
            progress={"linked_artifacts_processed": 0},
        )
    )

    assert out == {
        "linked_artifacts_processed": 2,
        "linked_artifacts_created": 2,
        "failed": 0,
        "created_doc_ids": created_ids,
        "removed_linked_artifact_documents_disabled": 4,
    }
    assert seen["link_urls"] == [
        "https://example.atlassian.net/wiki/spaces/PLAT/pages/42",
        "https://docs.example.com/design-spec",
    ]
    assert seen["seen_link_urls"] == {
        "https://example.atlassian.net/wiki/spaces/PLAT/pages/42",
        "https://docs.example.com/design-spec",
    }


def test_ingest_jira_issue_linked_artifacts_skips_reconcile_when_listing_is_truncated(monkeypatch) -> None:  # noqa: ANN001
    connectors = _import_connectors_with_lightweight_stubs()

    seen: dict[str, object] = {"reconciled": False}

    monkeypatch.setattr(
        connectors,
        "_jira_extract_linked_artifact_urls",
        lambda *_a, **_k: [
            "https://example.atlassian.net/wiki/spaces/PLAT/pages/42",
            "https://docs.example.com/design-spec",
            "https://docs.example.com/extra",
        ],
        raising=True,
    )
    monkeypatch.setattr(connectors, "_jira_project_run_cancelled", lambda *_a, **_k: False, raising=False)

    async def _fake_ingest_single_jira_linked_artifact(*_a, **_kwargs):  # noqa: ANN001
        return uuid.uuid4()

    def _fake_soft_disable(*_a, **_kwargs):  # noqa: ANN001
        seen["reconciled"] = True
        return 9

    monkeypatch.setattr(
        connectors,
        "_ingest_single_jira_linked_artifact",
        _fake_ingest_single_jira_linked_artifact,
        raising=False,
    )
    monkeypatch.setattr(
        connectors,
        "_soft_disable_jira_linked_artifact_documents_missing_from_issue",
        _fake_soft_disable,
        raising=True,
    )

    out = asyncio.run(
        connectors._ingest_jira_issue_linked_artifacts(
            object(),
            run=types.SimpleNamespace(id=uuid.uuid4(), dataset_id=uuid.uuid4(), status="running", stats={}),
            tenant_id=uuid.uuid4(),
            requested_by="tester",
            issue={"fields": {"description": "irrelevant"}},
            issue_info={
                "issue_id": "10000",
                "issue_key": "PLAT-42",
                "issue_url": "https://example.atlassian.net/browse/PLAT-42",
                "updated": "2026-03-02T12:34:56.000+0000",
            },
            effective_access={"mode": "inherit"},
            acl_provenance={"schema": "test-provenance"},
            settings_map={
                "base_url": "https://example.atlassian.net",
                "project_key": "PLAT",
                "include_linked_artifacts": True,
                "max_total_linked_artifacts": 5,
                "max_linked_artifacts_per_issue": 2,
                "include_comments": True,
                "max_comments_per_issue": 5,
                "auth_headers": {"Authorization": "Basic token"},
                "user_agent": "MimirQ-Jira/1.0",
                "parser_backend": "auto",
                "chunk_strategy": "langchain_recursive",
                "pipeline": {"ocr": True},
                "effective_mode": "full",
            },
            progress={"linked_artifacts_processed": 0},
        )
    )

    assert out["linked_artifacts_processed"] == 2
    assert out["linked_artifacts_created"] == 2
    assert out["failed"] == 0
    assert out["removed_linked_artifact_documents_disabled"] == 0
    assert seen["reconciled"] is False


def test_ingest_single_jira_attachment_sets_metadata_and_filename(monkeypatch) -> None:  # noqa: ANN001
    connectors = _import_connectors_with_lightweight_stubs()

    run_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    doc_id = uuid.uuid4()
    seen: dict[str, object] = {}

    class _DummyDB:
        def __init__(self) -> None:
            self.added: list[object] = []
            self.commits = 0

        def add(self, obj: object) -> None:
            self.added.append(obj)

        def commit(self) -> None:
            self.commits += 1

    class _DummyUrlUploadRequest:
        def __init__(self, **kwargs):  # noqa: ANN003
            for key, value in kwargs.items():
                setattr(self, key, value)

    dummy_db = _DummyDB()

    async def _fake_ingest_url_upload_request(*_a, **kwargs):  # noqa: ANN001
        body = kwargs["body"]
        seen["body_url"] = getattr(body, "url", None)
        seen["body_fetch_headers"] = getattr(body, "fetch_headers", None)
        seen["body_filename"] = getattr(body, "filename", None)
        doc = types.SimpleNamespace(id=doc_id, doc_metadata={})
        seen["doc"] = doc
        return doc

    def _fake_apply_document_access_from_config(*_a, **kwargs):  # noqa: ANN001
        seen["effective_access"] = kwargs.get("access")

    def _fake_apply_connector_identity_metadata(**kwargs):  # noqa: ANN001
        seen["identity_source_ref"] = kwargs.get("source_ref")
        seen["identity_source_id"] = kwargs.get("source_id")

    monkeypatch.setattr(connectors, "UrlUploadRequest", _DummyUrlUploadRequest, raising=False)
    monkeypatch.setattr(connectors, "_ingest_url_upload_request", _fake_ingest_url_upload_request, raising=False)
    monkeypatch.setattr(
        connectors,
        "_apply_document_access_from_config",
        _fake_apply_document_access_from_config,
        raising=False,
    )
    monkeypatch.setattr(
        connectors,
        "_apply_connector_identity_metadata",
        _fake_apply_connector_identity_metadata,
        raising=False,
    )

    created_id = asyncio.run(
        connectors._ingest_single_jira_attachment(
            dummy_db,
            run=types.SimpleNamespace(id=run_id, dataset_id=dataset_id),
            tenant_id=uuid.uuid4(),
            requested_by="tester",
            issue_info={
                "issue_id": "10000",
                "issue_key": "PLAT-42",
                "issue_url": "https://example.atlassian.net/browse/PLAT-42",
                "updated": "2026-03-02T12:34:56.000+0000",
            },
            attachment_ref={
                "attachment_id": "att-1",
                "filename": "design.pdf",
                "download_url": "https://example.atlassian.net/secure/attachment/10000/design.pdf",
            },
            effective_access={"mode": "partial_members"},
            acl_provenance={"schema": "test-provenance"},
            settings_map={
                "base_url": "https://example.atlassian.net",
                "project_key": "PLAT",
                "auth_headers": {"Authorization": "Basic token"},
                "user_agent": "MimirQ-Jira/1.0",
                "parser_backend": "auto",
                "chunk_strategy": "langchain_recursive",
                "pipeline": {"ocr": True},
                "effective_mode": "incremental",
            },
        )
    )

    assert created_id == doc_id
    assert seen["body_url"] == "https://example.atlassian.net/secure/attachment/10000/design.pdf"
    assert seen["body_fetch_headers"] == {"Authorization": "Basic token"}
    assert seen["body_filename"] == "design.pdf"
    assert seen["effective_access"] == {"mode": "partial_members"}
    assert seen["identity_source_ref"] == "att-1"
    assert seen["identity_source_id"] == "att-1"
    assert dummy_db.commits == 1
    assert len(dummy_db.added) == 1

    doc = seen["doc"]
    assert doc.doc_metadata["acl_provenance"] == {"schema": "test-provenance"}
    assert doc.doc_metadata["source_last_modified_source"] == connectors.JIRA_UPDATED_SOURCE
    assert doc.doc_metadata["connector"]["doc_kind"] == "attachment"
    assert doc.doc_metadata["connector"]["attachment_id"] == "att-1"
    assert doc.doc_metadata["connector"]["filename"] == "design.pdf"


def test_ingest_jira_issue_attachments_filters_extensions_and_reconciles(monkeypatch) -> None:  # noqa: ANN001
    connectors = _import_connectors_with_lightweight_stubs()

    created_id = uuid.uuid4()
    seen: dict[str, object] = {}

    monkeypatch.setattr(
        connectors,
        "_jira_extract_attachments",
        lambda *_a, **_k: [
            {
                "attachment_id": "att-1",
                "filename": "design.pdf",
                "download_url": "https://example.atlassian.net/secure/attachment/10000/design.pdf",
            },
            {
                "attachment_id": "att-2",
                "filename": "script.exe",
                "download_url": "https://example.atlassian.net/secure/attachment/10001/script.exe",
            },
        ],
        raising=True,
    )
    monkeypatch.setattr(connectors, "_jira_project_run_cancelled", lambda *_a, **_k: False, raising=False)
    monkeypatch.setattr(connectors.settings, "ALLOWED_EXTENSIONS", ".pdf", raising=False)

    async def _fake_ingest_single_jira_attachment(*_a, **kwargs):  # noqa: ANN001
        seen.setdefault("attachment_ids", []).append(kwargs.get("attachment_ref", {}).get("attachment_id"))
        return created_id

    def _fake_soft_disable(*_a, **kwargs):  # noqa: ANN001
        seen["seen_attachment_urls"] = set(kwargs.get("seen_attachment_urls") or set())
        return 5

    monkeypatch.setattr(
        connectors,
        "_ingest_single_jira_attachment",
        _fake_ingest_single_jira_attachment,
        raising=False,
    )
    monkeypatch.setattr(
        connectors,
        "_soft_disable_jira_attachment_documents_missing_from_issue",
        _fake_soft_disable,
        raising=True,
    )

    out = asyncio.run(
        connectors._ingest_jira_issue_attachments(
            object(),
            run=types.SimpleNamespace(id=uuid.uuid4(), dataset_id=uuid.uuid4(), status="running", stats={}),
            tenant_id=uuid.uuid4(),
            requested_by="tester",
            issue={
                "fields": {
                    "attachment": [
                        {"id": "att-1"},
                        {"id": "att-2"},
                    ]
                }
            },
            issue_info={
                "issue_id": "10000",
                "issue_key": "PLAT-42",
                "issue_url": "https://example.atlassian.net/browse/PLAT-42",
                "updated": "2026-03-02T12:34:56.000+0000",
            },
            effective_access={"mode": "inherit"},
            acl_provenance={"schema": "test-provenance"},
            settings_map={
                "base_url": "https://example.atlassian.net",
                "project_key": "PLAT",
                "include_attachments": True,
                "max_total_attachments": 5,
                "max_attachments_per_issue": 2,
                "auth_headers": {"Authorization": "Basic token"},
                "user_agent": "MimirQ-Jira/1.0",
                "parser_backend": "auto",
                "chunk_strategy": "langchain_recursive",
                "pipeline": {"ocr": True},
                "effective_mode": "full",
            },
            progress={"attachments_processed": 0},
        )
    )

    assert out == {
        "attachments_processed": 2,
        "attachments_created": 1,
        "failed": 0,
        "created_doc_ids": [created_id],
        "removed_attachment_documents_disabled": 5,
    }
    assert seen["attachment_ids"] == ["att-1"]
    assert seen["seen_attachment_urls"] == {
        "https://example.atlassian.net/secure/attachment/10000/design.pdf",
        "https://example.atlassian.net/secure/attachment/10001/script.exe",
    }


def test_ingest_jira_issue_attachments_skips_reconcile_when_listing_is_truncated(monkeypatch) -> None:  # noqa: ANN001
    connectors = _import_connectors_with_lightweight_stubs()

    seen: dict[str, object] = {"reconciled": False}

    monkeypatch.setattr(
        connectors,
        "_jira_extract_attachments",
        lambda *_a, **_k: [
            {
                "attachment_id": "att-1",
                "filename": "design.pdf",
                "download_url": "https://example.atlassian.net/secure/attachment/10000/design.pdf",
            },
            {
                "attachment_id": "att-2",
                "filename": "notes.txt",
                "download_url": "https://example.atlassian.net/secure/attachment/10001/notes.txt",
            },
        ],
        raising=True,
    )
    monkeypatch.setattr(connectors, "_jira_project_run_cancelled", lambda *_a, **_k: False, raising=False)
    monkeypatch.setattr(connectors.settings, "ALLOWED_EXTENSIONS", ".pdf,.txt", raising=False)

    async def _fake_ingest_single_jira_attachment(*_a, **_kwargs):  # noqa: ANN001
        return uuid.uuid4()

    def _fake_soft_disable(*_a, **_kwargs):  # noqa: ANN001
        seen["reconciled"] = True
        return 9

    monkeypatch.setattr(
        connectors,
        "_ingest_single_jira_attachment",
        _fake_ingest_single_jira_attachment,
        raising=False,
    )
    monkeypatch.setattr(
        connectors,
        "_soft_disable_jira_attachment_documents_missing_from_issue",
        _fake_soft_disable,
        raising=True,
    )

    out = asyncio.run(
        connectors._ingest_jira_issue_attachments(
            object(),
            run=types.SimpleNamespace(id=uuid.uuid4(), dataset_id=uuid.uuid4(), status="running", stats={}),
            tenant_id=uuid.uuid4(),
            requested_by="tester",
            issue={
                "fields": {
                    "attachment": [
                        {"id": "att-1"},
                        {"id": "att-2"},
                        {"id": "att-3"},
                    ]
                }
            },
            issue_info={
                "issue_id": "10000",
                "issue_key": "PLAT-42",
                "issue_url": "https://example.atlassian.net/browse/PLAT-42",
                "updated": "2026-03-02T12:34:56.000+0000",
            },
            effective_access={"mode": "inherit"},
            acl_provenance={"schema": "test-provenance"},
            settings_map={
                "base_url": "https://example.atlassian.net",
                "project_key": "PLAT",
                "include_attachments": True,
                "max_total_attachments": 5,
                "max_attachments_per_issue": 2,
                "auth_headers": {"Authorization": "Basic token"},
                "user_agent": "MimirQ-Jira/1.0",
                "parser_backend": "auto",
                "chunk_strategy": "langchain_recursive",
                "pipeline": {"ocr": True},
                "effective_mode": "full",
            },
            progress={"attachments_processed": 0},
        )
    )

    assert out["attachments_processed"] == 2
    assert out["attachments_created"] == 2
    assert out["failed"] == 0
    assert out["removed_attachment_documents_disabled"] == 0
    assert seen["reconciled"] is False


def test_finalize_cancelled_jira_project_run_sets_finished_at_and_syncs(monkeypatch) -> None:  # noqa: ANN001
    connectors = _import_connectors_with_lightweight_stubs()

    seen: dict[str, object] = {}

    class _DummyDB:
        def __init__(self) -> None:
            self.commits = 0

        def commit(self) -> None:
            self.commits += 1

    def _fake_sync(*_a, **kwargs):  # noqa: ANN001
        seen["synced_run"] = kwargs.get("run")

    dummy_db = _DummyDB()
    run = types.SimpleNamespace(finished_at=None, stats={"keep": "me"})

    monkeypatch.setattr(connectors, "_sync_connector_config_from_run", _fake_sync, raising=False)

    connectors._finalize_cancelled_jira_project_run(dummy_db, run=run)

    assert run.finished_at is not None
    assert run.stats["keep"] == "me"
    assert dummy_db.commits == 1
    assert seen["synced_run"] is run


def test_finalize_jira_project_run_updates_stats_and_audit(monkeypatch) -> None:  # noqa: ANN001
    connectors = _import_connectors_with_lightweight_stubs()
    import app.services.audit_log_service as audit_log_service

    created_doc_ids = [uuid.uuid4(), uuid.uuid4()]
    run_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    seen: dict[str, object] = {}

    class _DummyDB:
        def __init__(self) -> None:
            self.commits = 0

        def commit(self) -> None:
            self.commits += 1

    def _fake_reconcile(*_a, **kwargs):  # noqa: ANN001
        seen["reconcile_kwargs"] = dict(kwargs)
        return 3, 4

    def _fake_audit_log_event(*_a, **kwargs):  # noqa: ANN001
        seen["audit_action"] = kwargs.get("action")
        seen["audit_details"] = dict(kwargs.get("details") or {})

    def _fake_sync(*_a, **kwargs):  # noqa: ANN001
        seen["synced_run"] = kwargs.get("run")

    dummy_db = _DummyDB()
    run = types.SimpleNamespace(
        id=run_id,
        dataset_id=dataset_id,
        status="running",
        stats={"keep": "me"},
        finished_at=None,
    )

    monkeypatch.setattr(
        connectors,
        "_soft_disable_jira_documents_missing_from_full_sync",
        _fake_reconcile,
        raising=True,
    )
    monkeypatch.setattr(audit_log_service, "audit_log_event", _fake_audit_log_event, raising=True)
    monkeypatch.setattr(connectors, "_sync_connector_config_from_run", _fake_sync, raising=False)

    connectors._finalize_jira_project_run(
        dummy_db,
        run=run,
        run_id=run_id,
        tenant_id=uuid.uuid4(),
        requested_by="tester",
        settings_map={
            "effective_mode": "full",
            "base_url": "https://example.atlassian.net",
            "project_key": "PLAT",
            "enable_source_acl": True,
            "source_acl_fallback_mode": "partial_members",
        },
        progress={
            "created": 7,
            "failed": 1,
            "created_doc_ids": created_doc_ids,
            "delta_acl_docs_updated": 2,
            "delta_acl_sources_updated": 1,
            "removed_issues_reconciled": 0,
            "removed_documents_disabled": 0,
            "attachments_processed": 3,
            "attachments_created": 2,
            "removed_attachment_documents_disabled": 1,
            "linked_artifacts_processed": 4,
            "linked_artifacts_created": 3,
            "removed_linked_artifact_documents_disabled": 2,
            "skipped_boundary_duplicates": 1,
            "last_modified_seen": "2026-03-02T12:34:56.000+0000",
            "last_modified_ids_seen": {"10000", "10001"},
        },
        observed_issue_urls={"https://example.atlassian.net/browse/PLAT-42"},
        listing_complete=True,
    )

    assert (seen.get("reconcile_kwargs") or {}).get("project_key") == "PLAT"
    assert run.stats["keep"] == "me"
    assert run.stats["document_ids"] == [str(doc_id) for doc_id in created_doc_ids]
    assert run.stats["acl_delta_sync_updated_documents"] == 2
    assert run.stats["acl_delta_sync_updated_sources"] == 1
    assert run.stats["removed_issues_reconciled"] == 3
    assert run.stats["removed_documents_disabled"] == 4
    assert run.stats["processed_attachments"] == 3
    assert run.stats["created_attachments"] == 2
    assert run.stats["removed_attachment_documents_disabled"] == 1
    assert run.stats["processed_linked_artifacts"] == 4
    assert run.stats["created_linked_artifacts"] == 3
    assert run.stats["removed_linked_artifact_documents_disabled"] == 2
    assert run.stats["skipped_boundary_duplicates"] == 1
    assert run.stats["last_modified"] == "2026-03-02T12:34:56.000+0000"
    assert run.stats["last_modified_ids"] == ["10000", "10001"]
    assert run.finished_at is not None
    assert run.status == connectors._connector_run_completion_status(created=7, failed=1)
    assert seen["audit_action"] == "jira_project.source_acl.delta_sync"
    assert (seen.get("audit_details") or {}).get("updated_documents") == 2
    assert (seen.get("audit_details") or {}).get("updated_sources") == 1
    assert dummy_db.commits == 1
    assert seen["synced_run"] is run

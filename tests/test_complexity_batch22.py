import uuid
from typing import Any

from app.connectors.db import catalog_runner
from app.services import report_html


class _StoreRecorder:
    def __init__(self) -> None:
        self.tables: list[dict[str, Any]] = []
        self.replaced_columns: list[list[catalog_runner.CatalogColumnInput]] = []
        self.snapshots: list[dict[str, Any]] = []

    def upsert_table(
        self,
        *,
        tenant_id: uuid.UUID,
        dataset_id: uuid.UUID,
        connector_config_id: uuid.UUID | None,
        table: catalog_runner.CatalogTableInput,
        seen_at: Any,
    ) -> uuid.UUID:
        self.tables.append(
            {
                "tenant_id": tenant_id,
                "dataset_id": dataset_id,
                "connector_config_id": connector_config_id,
                "table": table,
                "seen_at": seen_at,
            }
        )
        return uuid.uuid4()

    def replace_columns(self, *, table_id: uuid.UUID, columns: list[catalog_runner.CatalogColumnInput]) -> int:
        _ = table_id
        self.replaced_columns.append(list(columns))
        return len(columns)

    def insert_profile_snapshot(
        self,
        *,
        table_id: uuid.UUID,
        entitlement_hash: str,
        profile: dict[str, Any],
        sample_meta: dict[str, Any],
    ) -> uuid.UUID:
        self.snapshots.append(
            {
                "table_id": table_id,
                "entitlement_hash": entitlement_hash,
                "profile": profile,
                "sample_meta": sample_meta,
            }
        )
        return uuid.uuid4()


class _FakeResult:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def mappings(self) -> "_FakeResult":
        return self

    def all(self) -> list[dict[str, Any]]:
        return list(self._rows)


class _FakeMysqlConnection:
    def __init__(self) -> None:
        self.sql: list[str] = []

    def execute(self, stmt: Any) -> _FakeResult:
        sql = str(stmt)
        self.sql.append(sql)
        if "`bad`" in sql:
            raise RuntimeError("boom")
        if "`fallback`" in sql:
            return _FakeResult([])
        if "`full`" in sql:
            return _FakeResult(
                [
                    {"id": 1, "name": "Alice", "note": "first"},
                    {"id": 2, "name": "Bob", "note": "second"},
                ]
            )
        raise AssertionError(sql)


class _FakeMysqlContext:
    def __init__(self) -> None:
        self.conn = _FakeMysqlConnection()
        self.exited = False

    def __enter__(self) -> _FakeMysqlConnection:
        return self.conn

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        _ = (exc_type, exc, tb)
        self.exited = True
        return False


def test_scrub_report_for_redaction_keeps_objective_metrics_only() -> None:
    report = {
        "dataset_name": "Secret Dataset",
        "dataset_id": "dataset-123",
        "profile": {
            "generated_at": "2026-01-01T00:00:00Z",
            "total_documents": 3,
            "by_status": {"done": 3},
            "by_directory": {"secret/finance": 3},
        },
        "governance_metrics": {
            "docs_with_governance": 2,
            "nested": {"safe": 1, "secret": "drop-me"},
            "notes": "drop-me",
        },
        "latest_regression_run": {
            "status": "done",
            "metrics": ["hit@1"],
            "summary": {"score": 0.75, "notes": "drop-me", "nested": [1, "drop-me"]},
        },
        "retrieval_audit": {
            "status": "failed",
            "failure_categories": {"missing": 2},
            "plugin_refs": ["private-plugin"],
        },
    }

    scrubbed = report_html._scrub_report_for_redaction(report)

    assert scrubbed["dataset_name"] == report_html.REDACTED_TEXT
    assert scrubbed["dataset_id"] == report_html.REDACTED_TEXT
    assert "by_directory" not in scrubbed["profile"]
    assert scrubbed["governance_metrics"] == {"docs_with_governance": 2, "nested": {"safe": 1}}
    assert scrubbed["latest_regression_run"]["summary"] == {"score": 0.75, "nested": [1]}
    assert scrubbed["retrieval_audit"] == {"status": "failed", "failure_categories": {"missing": 2}}


def test_render_rag_audit_html_redacts_directory_slice_and_precheck_scan_id() -> None:
    html = report_html.render_rag_audit_html(
        title="RAG <Audit>",
        dataset_name="Dataset",
        dataset_id="dataset-1",
        generated_at="2026-01-01T00:00:00Z",
        redact=True,
        report={
            "profile": {
                "total_documents": 2,
                "by_status": {"done": 2},
                "by_file_type": {"pdf": 2},
                "length_percentiles": {"p50": 1, "p90": 2},
                "chunk_token_percentiles": {"p50": 3},
                "chunk_coverage_percentiles": {"p50": 4},
            },
            "precheck_summary": {
                "scan_run_id": "scan-secret",
                "generated_at": "2026-01-01T00:00:00Z",
                "total_files": 2,
                "total_size_bytes": 99,
                "by_file_type": {"pdf": 2},
                "language_mix": {"zh": 2},
                "directory_stats": [{"path": "secret/dir", "total_files": 2, "risky_files": 1, "total_size_bytes": 99}],
                "pdf_scan": {"scanned": 1, "not_scanned": 1, "unknown": 0},
            },
            "latest_regression_run": {
                "status": "done",
                "created_at": "2026-01-02T00:00:00Z",
                "finished_at": "2026-01-03T00:00:00Z",
                "summary": {
                    "retrieval_hit_at_1": 0.5,
                    "retrieval_slices": {
                        "file_type": {"buckets": [{"key": "pdf", "items": 2, "retrieval_recall": 0.5}]},
                        "language": {"buckets": [{"key": "zh", "items": 2, "retrieval_recall": 0.6}]},
                        "directory": {"buckets": [{"key": "secret/dir", "items": 2, "retrieval_recall": 0.7}]},
                    },
                },
            },
        },
    )

    assert "RAG &lt;Audit&gt;" in html
    assert "scan-secret" not in html
    assert "secret/dir" not in html
    assert "已脱敏：directory 不展示" in html


def test_render_precheck_html_redacts_root_and_directory_structure() -> None:
    html = report_html.render_precheck_html(
        title="Preview <Check>",
        dataset_name="Sensitive Name",
        dataset_id="dataset-1",
        root_path="/srv/secret/root",
        generated_at="2026-01-01T00:00:00Z",
        redact=True,
        summary={
            "total_files": 4,
            "total_size_bytes": 2048,
            "length_percentiles": {"p50": 10, "p90": 50},
            "token_percentiles": {"p50": 5, "p90": 25_000},
            "pdf_scan": {"scanned": 1, "not_scanned": 2, "unknown": 1},
            "by_file_type": {"pdf": 4},
            "language_mix": {"zh": 4},
            "pii_hits_total": {"email": 1},
            "secrets_hits_total": {"token": 1},
            "primary_tag_counts": {"finance": 4},
            "processing_path_counts": {"ocr": 4},
            "findings": [{"key": "empty_text", "label": "Empty Text", "count": 1}],
            "directory_stats": [{"path": "dept/secret", "total_files": 4, "risky_files": 2, "total_size_bytes": 2048}],
            "pdf_detection": {
                "sample_pages": "<2>",
                "scan_max_chars_per_page": 10,
                "text_min_chars_per_page": 20,
                "scan_ratio_threshold": 0.8,
            },
        },
        samples={
            "representative": [{"name": "sample.pdf", "file_type": "pdf", "file_size": 128}],
            "needs_review": {"ocr": [{}]},
        },
    )

    assert "Preview &lt;Check&gt;" in html
    assert "/srv/secret/root" not in html
    assert "dept/secret" not in html
    assert "已脱敏：目录结构不展示" in html
    assert "P90 文本长度较长" in html


def test_run_catalog_sync_sqlserver_normalizes_schema_columns_and_profiles(monkeypatch: Any) -> None:
    store = _StoreRecorder()
    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    connector_config_id = uuid.uuid4()

    monkeypatch.setattr(
        catalog_runner,
        "_introspect_sqlserver",
        lambda **_kwargs: [
            {
                "db_name": "analytics",
                "schema_name": "dbo",
                "table_name": "orders",
                "table_type": "VIEW",
                "comment": "main",
                "row_count_estimate": "17",
                "columns": [
                    {"ordinal": 1, "name": "order_id", "data_type": "bigint", "nullable": False, "comment": "pk"},
                    {"ordinal": "oops", "name": "created_at", "data_type": "timestamp"},
                ],
            },
            {"db_name": "analytics", "schema_name": "dbo", "table_name": "ignored", "columns": []},
        ],
    )

    result = catalog_runner.run_catalog_sync(
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        connector_id="sqlserver_catalog",
        connector_config_id=connector_config_id,
        config={"database": "analytics", "max_tables": 1, "profile_enabled": True, "password": "secret"},
        store=store,
    )

    assert result["engine"] == "sqlserver"
    assert result["tables"] == 1
    assert result["tables_upserted"] == 1
    assert result["columns_upserted"] == 2
    assert result["profiles_written"] == 1
    assert len(result["entitlement_hash"]) == 64

    persisted = store.tables[0]["table"]
    assert persisted.schema_name == "dbo"
    assert persisted.table_name == "orders"
    assert persisted.table_type == "view"
    assert [column.name for column in persisted.columns] == ["order_id", "created_at"]
    assert persisted.columns[1].ordinal == 0

    snapshot = store.snapshots[0]
    assert snapshot["entitlement_hash"] == result["entitlement_hash"]
    assert snapshot["profile"] == {"row_count_estimate": 17}
    assert snapshot["sample_meta"]["strategy"] == "catalog_sync"


def test_extract_row_snapshots_mysql_preserves_limits_fallback_skip_and_cleanup(monkeypatch: Any) -> None:
    ctx = _FakeMysqlContext()
    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()

    monkeypatch.setattr(
        catalog_runner,
        "_introspect_mysql",
        lambda **_kwargs: [
            {"db_name": "analytics", "table_name": "bad", "columns": [{"name": "ignored"}]},
            {
                "db_name": "analytics",
                "table_name": "fallback",
                "columns": [{"name": "declared_one"}, {"name": "declared_two"}, {"name": "declared_three"}],
            },
            {
                "db_name": "analytics",
                "table_name": "full",
                "columns": [{"name": "id"}, {"name": "name"}, {"name": "note"}],
            },
        ],
    )
    monkeypatch.setattr(catalog_runner, "_connect_mysql", lambda _config: ctx)

    snapshots = catalog_runner.extract_row_snapshots(
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        connector_id="mysql_catalog",
        config={"database": "analytics"},
        max_tables=2,
        max_rows_per_table=1,
        max_cols=2,
    )

    assert ctx.exited is True
    assert [snapshot["source_table"] for snapshot in snapshots] == ["analytics.fallback", "analytics.full"]

    fallback_snapshot, full_snapshot = snapshots
    assert fallback_snapshot["columns"] == ["declared_one", "declared_two", "__row_pk_hash"]
    assert fallback_snapshot["rows"] == []
    assert len(fallback_snapshot["source_sync_token"]) == 64

    assert full_snapshot["columns"] == ["id", "name", "__row_pk_hash"]
    assert len(full_snapshot["rows"]) == 1
    assert set(full_snapshot["rows"][0]) == {"id", "name", "__row_pk_hash"}
    assert full_snapshot["rows"][0]["id"] == 1
    assert len(full_snapshot["rows"][0]["__row_pk_hash"]) == 64

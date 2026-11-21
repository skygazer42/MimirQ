import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

import app.services.connectors.execution.confluence as connectors_confluence
import app.services.connectors.execution.shared.artifacts as connectors_artifacts
import app.services.connectors.execution.url_batch as connectors_url_batch
from app.models.connectors.runs import ConnectorRun, ConnectorRunDocument
from app.models.documents.records import Document as DBDocument


class _FakeQuery:
    def __init__(self, first_result=None) -> None:
        self._first_result = first_result

    def filter(self, *_args, **_kwargs):  # noqa: ANN002, ANN003
        return self

    def first(self):
        return self._first_result


class _FakeDB:
    def __init__(self) -> None:
        self.added: list[object] = []

    def query(self, _model):  # noqa: ANN001
        return _FakeQuery()

    def add(self, obj: object) -> None:
        self.added.append(obj)

    def commit(self) -> None:
        return None

    def refresh(self, obj: object) -> None:
        if getattr(obj, "id", None) is None:
            obj.id = uuid4()


class _SequenceDB(_FakeDB):
    def __init__(self, first_results: list[object | None]) -> None:
        super().__init__()
        self._first_results = iter(first_results)

    def query(self, _model):  # noqa: ANN001
        return _FakeQuery(next(self._first_results))


def _make_run(*, connector_id: str, config_id: str | None) -> ConnectorRun:
    stats = {"config_id": config_id} if config_id else {}
    return ConnectorRun(
        id=uuid4(),
        tenant_id=uuid4(),
        dataset_id=uuid4(),
        connector_id=connector_id,
        requested_by="tester",
        status="running",
        config={},
        stats=stats,
    )


@pytest.mark.parametrize("connector_id", ["github_repo", "drive_files"])
def test_removed_connector_config_actions_reject_before_writing(monkeypatch, connector_id: str) -> None:
    from app.api.schemas.sources import ConnectorConfigCreateRequest
    from app.services.connectors import configs, schedules

    tenant_id = uuid4()
    dataset_id = uuid4()
    saved = SimpleNamespace(id=uuid4(), connector_id=connector_id, dataset_id=dataset_id)
    db = _SequenceDB([saved, saved, saved])
    monkeypatch.setattr(configs.dataset_service, "ensure_member", lambda *_args: None)
    monkeypatch.setattr(configs.dataset_service, "get_dataset", lambda *_args: object())
    monkeypatch.setattr(configs.dataset_service, "assert_dataset_writable", lambda *_args: None)

    async def prepare(operation, **_kwargs):
        return operation(db)

    monkeypatch.setattr(configs, "prepare_managed_handoff", prepare)
    payload = ConnectorConfigCreateRequest(connector_id=connector_id, dataset_id=dataset_id, name="Removed source")
    with pytest.raises(HTTPException, match="Unsupported connector_id") as error:
        configs.create_config(payload, tenant_id=tenant_id, account_id="operator", db=db)
    assert error.value.status_code == 400
    with pytest.raises(HTTPException, match="Unsupported connector_id") as error:
        asyncio.run(configs.run_saved_config(saved.id, object(), tenant_id=tenant_id, account_id="operator", db=db))
    assert error.value.status_code == 400
    with pytest.raises(HTTPException, match="Unsupported connector_id") as error:
        configs.reconcile_config(saved.id, apply=True, tenant_id=tenant_id, account_id="operator", db=db)
    assert error.value.status_code == 400
    assert db.added == []
    monkeypatch.setattr(schedules, "_is_scheduled_config_due", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(schedules, "_config_dataset_is_writable", lambda *_args: True)
    result = schedules._prepare_scheduled_config(
        db,
        config_id=saved.id,
        tenant_id=tenant_id,
        account_id="operator",
        now=datetime(2026, 11, 17, tzinfo=UTC),
        background_tasks=object(),
    )
    assert result == ("skipped", None, None)
    assert saved.last_error == "unsupported_connector_id"
    assert db.added == []


def test_db_row_sidecar_paths_are_config_scoped_and_legacy_safe() -> None:
    dataset_id = uuid4()
    connector_id = "mysql"
    config_id = str(uuid4())

    assert (
        connectors_artifacts._db_row_sidecar_file_path(
            dataset_id=dataset_id,
            connector_id=connector_id,
        )
        == f"virtual://db_catalog/rows/{dataset_id}/{connector_id}"
    )
    assert (
        connectors_artifacts._db_row_sidecar_filename(
            dataset_id=dataset_id,
            connector_id=connector_id,
        )
        == f"db_rows_{connector_id}_{dataset_id}.sqlite"
    )
    assert (
        connectors_artifacts._db_row_sidecar_file_path(
            dataset_id=dataset_id,
            connector_id=connector_id,
            connector_config_id=config_id,
        )
        == f"virtual://db_catalog/rows/{dataset_id}/{connector_id}/{config_id}"
    )
    assert (
        connectors_artifacts._db_row_sidecar_filename(
            dataset_id=dataset_id,
            connector_id=connector_id,
            connector_config_id=config_id,
        )
        == f"db_rows_{connector_id}_{config_id}_{dataset_id}.sqlite"
    )


def test_upsert_db_row_sidecar_document_uses_config_scoped_identity(monkeypatch) -> None:
    config_id = str(uuid4())
    run = _make_run(connector_id="sqlserver", config_id=config_id)
    db = _FakeDB()

    monkeypatch.setattr(
        connectors_artifacts,
        "_now",
        lambda: SimpleNamespace(isoformat=lambda: "2026-07-25T00:00:00+00:00"),
        raising=True,
    )
    monkeypatch.setattr(connectors_artifacts, "_connector_config_id_from_run", lambda _run: config_id, raising=True)

    monkeypatch.setattr(
        "app.services.tables.store.import_db_row_snapshots",
        lambda **_kwargs: [
            SimpleNamespace(
                table_id=uuid4(),
                sheet_index=0,
                sheet_name="users",
                row_count=1,
                col_count=1,
                truncated=False,
                columns=["id"],
                sample_rows=[{"id": 1}],
                row_source_table="public.users",
                row_source_sync_token="tok-1",
                row_source_pk_hash_col="id_hash",
            )
        ],
        raising=True,
    )

    result = connectors_artifacts._upsert_db_row_sidecar_document(
        db=db,
        run=run,
        connector_id="sqlserver",
        requested_by="tester",
        snapshots=[{"source_table": "public.users", "source_sync_token": "tok-1"}],
        max_tables=1,
        max_rows_per_table=1,
        max_cols=1,
    )

    created_doc = next(obj for obj in db.added if isinstance(obj, DBDocument))
    created_link = next(obj for obj in db.added if isinstance(obj, ConnectorRunDocument))

    assert result == {
        "document_id": str(created_doc.id),
        "tables": 1,
        "source_manifest_count": 1,
    }
    assert created_doc.file_path == f"virtual://db_catalog/rows/{run.dataset_id}/sqlserver/{config_id}"
    assert created_doc.filename == f"db_rows_sqlserver_{config_id}_{run.dataset_id}.sqlite"
    assert created_doc.doc_metadata["connector"]["config_id"] == config_id
    assert created_doc.doc_metadata["connector"]["source_ref"] == f"db_catalog_rows:sqlserver:{config_id}"
    assert created_link.source_ref == f"db_catalog_rows:sqlserver:{config_id}"


def test_upsert_db_row_sidecar_document_migrates_matching_legacy_identity(monkeypatch) -> None:
    config_id = str(uuid4())
    run = _make_run(connector_id="sqlserver", config_id=config_id)
    legacy_doc = SimpleNamespace(
        id=uuid4(),
        tenant_id=run.tenant_id,
        dataset_id=run.dataset_id,
        filename=f"db_rows_sqlserver_{run.dataset_id}.sqlite",
        file_type="dbrows",
        file_size=0,
        file_path=f"virtual://db_catalog/rows/{run.dataset_id}/sqlserver",
        doc_metadata={"connector": {"config_id": config_id}},
    )
    db = _SequenceDB([None, legacy_doc, None])

    monkeypatch.setattr(
        connectors_artifacts,
        "_now",
        lambda: SimpleNamespace(isoformat=lambda: "2026-07-25T00:00:00+00:00"),
        raising=True,
    )
    monkeypatch.setattr(connectors_artifacts, "_connector_config_id_from_run", lambda _run: config_id, raising=True)
    monkeypatch.setattr(
        "app.services.tables.store.import_db_row_snapshots",
        lambda **_kwargs: [],
        raising=True,
    )

    result = connectors_artifacts._upsert_db_row_sidecar_document(
        db=db,
        run=run,
        connector_id="sqlserver",
        requested_by="tester",
        snapshots=[{"source_table": "public.users", "source_sync_token": "tok-1"}],
        max_tables=1,
        max_rows_per_table=1,
        max_cols=1,
    )

    assert result == {
        "document_id": str(legacy_doc.id),
        "tables": 0,
        "source_manifest_count": 1,
    }


def test_url_batch_connector_reuses_shared_url_ingest_helper(monkeypatch) -> None:
    import app.services.documents.ingestion as ingestion_service

    run = _make_run(connector_id="url_batch", config_id=None)
    db = _FakeDB()
    calls: list[dict[str, object]] = []

    async def _shared_ingest(**kwargs):  # noqa: ANN003, ANN202
        calls.append(dict(kwargs))
        return SimpleNamespace(id=uuid4(), doc_metadata={})

    monkeypatch.setattr(ingestion_service, "ingest_url", _shared_ingest, raising=True)
    monkeypatch.setattr(
        connectors_url_batch, "_apply_document_access_from_config", lambda *_a, **_k: None, raising=True
    )
    monkeypatch.setattr(
        connectors_url_batch, "_apply_connector_identity_metadata", lambda *_a, **_k: None, raising=True
    )

    document_id = asyncio.run(
        connectors_url_batch._ingest_url_batch_url(
            db,
            run=run,
            run_id=run.id,
            tenant_id=run.tenant_id,
            requested_by="tester",
            url="https://example.com/doc.txt",
            settings_map={
                "filename": "doc.txt",
                "parser_backend": "auto",
                "chunk_strategy": "langchain_recursive",
                "pipeline": None,
            },
        )
    )

    assert calls and calls[0]["background_tasks"] is None
    assert calls[0]["tenant_id"] == run.tenant_id
    assert calls[0]["db"] is db
    assert calls[0]["body"].url == "https://example.com/doc.txt"
    assert document_id


def test_confluence_api_view_connector_reuses_shared_local_html_ingest_helper(monkeypatch) -> None:
    run = _make_run(connector_id="confluence_space", config_id=None)
    db = _FakeDB()
    calls: list[dict[str, object]] = []

    async def _shared_local_html(**kwargs):  # noqa: ANN003, ANN202
        calls.append(dict(kwargs))
        return SimpleNamespace(id=uuid4(), doc_metadata={})

    async def _fetch_html(*_args, **_kwargs):  # noqa: ANN202
        return "<div>body</div>"

    monkeypatch.setattr(connectors_confluence, "_fetch_confluence_page_view_html", _fetch_html, raising=True)
    monkeypatch.setattr(
        connectors_confluence, "LocalHtmlIngestRequest", lambda **kwargs: SimpleNamespace(**kwargs), raising=True
    )
    monkeypatch.setattr(connectors_confluence.ingestion_service, "ingest_html", _shared_local_html, raising=True)

    asyncio.run(
        connectors_confluence._ingest_confluence_page_api_view(
            object(),
            db,
            run=run,
            tenant_id=run.tenant_id,
            requested_by="tester",
            page_id="123",
            title="Confluence Title",
            page_url="https://confluence.example/wiki/page",
            filename="page.html",
            settings_map={
                "parser_backend": "auto",
                "chunk_strategy": "langchain_recursive",
                "pipeline": None,
            },
        )
    )

    assert calls and calls[0]["background_tasks"] is None
    assert calls[0]["tenant_id"] == run.tenant_id
    assert calls[0]["db"] is db
    assert calls[0]["body"].source_url == "https://confluence.example/wiki/page"
    assert calls[0]["body"].filename == "page.html"
    assert "Confluence Title" in calls[0]["body"].html

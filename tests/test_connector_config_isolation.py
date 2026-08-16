import asyncio
from types import SimpleNamespace
from uuid import uuid4

from app.api.v1 import (
    connectors_artifacts,
    connectors_confluence,
    connectors_drive_files,
    connectors_github_repo,
    connectors_url_batch,
)
from app.models.connector import ConnectorRun, ConnectorRunDocument
from app.models.document import Document as DBDocument


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


def test_drive_files_acl_paths_use_run_config_id(monkeypatch) -> None:
    config_id = str(uuid4())
    run = _make_run(connector_id="drive_files", config_id=config_id)
    db = _FakeDB()
    delta_calls: list[dict[str, object]] = []
    disable_ref_calls: list[dict[str, object]] = []
    disable_url_calls: list[dict[str, object]] = []

    async def _resolve_drive_source_acl(*_args, **_kwargs):  # noqa: ANN002, ANN003
        return {"mode": "inherit"}, {"source": "acl"}

    async def _ingest_url_upload_request(**_kwargs):  # noqa: ANN003
        return SimpleNamespace(id=uuid4(), doc_metadata={})

    monkeypatch.setattr(
        connectors_drive_files,
        "_resolve_drive_source_acl",
        _resolve_drive_source_acl,
        raising=True,
    )
    monkeypatch.setattr(
        connectors_drive_files,
        "_leader_module",
        SimpleNamespace(
            _drive_direct_download_url=lambda file_id: f"https://download/{file_id}",
            _delta_sync_connector_documents_acl_by_source_url=lambda *_args, **kwargs: delta_calls.append(kwargs) or 2,
            UrlUploadRequest=lambda **kwargs: SimpleNamespace(**kwargs),
            _ingest_url_upload_request=_ingest_url_upload_request,
            _apply_document_access_from_config=lambda *_args, **_kwargs: None,
            _apply_connector_identity_metadata=lambda *_args, **_kwargs: None,
            _connector_config_id_from_run=lambda _run: config_id,
            _soft_disable_connector_documents_by_source_ref=lambda *_args, **kwargs: (
                disable_ref_calls.append(kwargs) or 1
            ),
            _soft_disable_connector_documents_by_source_url=lambda *_args, **kwargs: (
                disable_url_calls.append(kwargs) or 1
            ),
        ),
        raising=False,
    )

    result = asyncio.run(
        connectors_drive_files._ingest_drive_file_source(
            client=object(),
            db=db,
            run=run,
            run_id=uuid4(),
            tenant_id=run.tenant_id,
            requested_by="tester",
            source_ref="url:file-1",
            file_id="file-1",
            settings_map={"enable_source_acl": True},
        )
    )
    reconciled = connectors_drive_files._reconcile_removed_drive_sources(
        db,
        run=run,
        tenant_id=run.tenant_id,
        removed_source_refs=["url:file-1", "file-2"],
    )

    assert result["updated_existing"] == 2
    assert reconciled == (2, 2)
    assert delta_calls == [
        {
            "tenant_id": run.tenant_id,
            "dataset_id": run.dataset_id,
            "connector_id": "drive_files",
            "source_url": "https://download/file-1",
            "requested_by": "tester",
            "access": {"mode": "inherit"},
            "acl_provenance": {"source": "acl"},
            "connector_config_id": config_id,
        }
    ]
    assert [call["connector_config_id"] for call in disable_ref_calls] == [config_id]
    assert [call["connector_config_id"] for call in disable_url_calls] == [config_id]


def test_github_repo_acl_paths_use_run_config_id(monkeypatch) -> None:
    config_id = str(uuid4())
    run = _make_run(connector_id="github_repo", config_id=config_id)
    delta_calls: list[dict[str, object]] = []
    disable_calls: list[dict[str, object]] = []

    monkeypatch.setattr(
        connectors_github_repo,
        "_leader_module",
        SimpleNamespace(
            _connector_config_id_from_run=lambda _run: config_id,
            _delta_sync_connector_documents_acl_by_source_url=lambda *_args, **kwargs: delta_calls.append(kwargs) or 3,
            _github_raw_url=lambda **kwargs: (
                f"https://raw.example/{kwargs['owner']}/{kwargs['repo']}/{kwargs['branch']}/{kwargs['path']}"
            ),
            _soft_disable_connector_documents_by_source_url=lambda *_args, **kwargs: disable_calls.append(kwargs) or 1,
            _append_connector_error=lambda stats, **_kwargs: stats,
            _finalize_connector_stats=lambda stats: stats,
        ),
        raising=False,
    )

    source_acl_access = {"mode": "partial_members"}
    updated = connectors_github_repo._apply_github_repo_source_acl_delta_sync(
        object(),
        run=run,
        tenant_id=run.tenant_id,
        requested_by="tester",
        raw_url="https://raw.example/acme/repo/main/README.md",
        effective_access=source_acl_access,
        source_acl_context={
            "source_acl_access": source_acl_access,
            "source_acl_provenance": {"source": "acl"},
        },
    )
    reconciled = connectors_github_repo._reconcile_removed_github_repo_paths(
        object(),
        run=run,
        tenant_id=run.tenant_id,
        settings_map={"owner": "acme", "repo_name": "repo", "branch": "main"},
        removed_paths=["README.md"],
    )

    assert updated == 3
    assert reconciled == (1, 1)
    assert delta_calls == [
        {
            "tenant_id": run.tenant_id,
            "dataset_id": run.dataset_id,
            "connector_id": "github_repo",
            "source_url": "https://raw.example/acme/repo/main/README.md",
            "requested_by": "tester",
            "access": source_acl_access,
            "acl_provenance": {"source": "acl"},
            "connector_config_id": config_id,
        }
    ]
    assert [call["connector_config_id"] for call in disable_calls] == [config_id]


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
        "_leader_module",
        SimpleNamespace(
            _now=lambda: SimpleNamespace(isoformat=lambda: "2026-07-25T00:00:00+00:00"),
            _connector_config_id_from_run=lambda _run: config_id,
        ),
        raising=True,
    )

    monkeypatch.setattr(
        "app.services.table_store_service.import_db_row_snapshots",
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
        "_leader_module",
        SimpleNamespace(
            _now=lambda: SimpleNamespace(isoformat=lambda: "2026-07-25T00:00:00+00:00"),
            _connector_config_id_from_run=lambda _run: config_id,
        ),
        raising=True,
    )
    monkeypatch.setattr(
        "app.services.table_store_service.import_db_row_snapshots",
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
    import app.api.v1.connectors as connectors_module

    run = _make_run(connector_id="url_batch", config_id=None)
    db = _FakeDB()
    calls: list[dict[str, object]] = []

    async def _shared_ingest(**kwargs):  # noqa: ANN003, ANN202
        calls.append(dict(kwargs))
        return SimpleNamespace(id=uuid4(), doc_metadata={})

    monkeypatch.setattr(connectors_module, "_ingest_url_upload_request", _shared_ingest, raising=True)
    monkeypatch.setattr(connectors_module, "_apply_document_access_from_config", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(connectors_module, "_apply_connector_identity_metadata", lambda *_a, **_k: None, raising=True)

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
        connectors_confluence,
        "_leader_module",
        SimpleNamespace(
            LocalHtmlIngestRequest=lambda **kwargs: SimpleNamespace(**kwargs),
            _ingest_local_html_request=_shared_local_html,
        ),
        raising=False,
    )

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

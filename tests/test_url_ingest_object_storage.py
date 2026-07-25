import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import BackgroundTasks, HTTPException

from app.api.utils.url_ingest import DownloadedURL
from app.api.v1 import documents as documents_module
from app.types.pipeline import PipelineOptions


class _DB:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.commits = 0
        self.rollbacks = 0

    def add(self, obj) -> None:  # noqa: ANN001
        self.added.append(obj)

    def commit(self) -> None:
        self.commits += 1

    def refresh(self, _obj) -> None:  # noqa: ANN001
        return None

    def rollback(self) -> None:
        self.rollbacks += 1


@pytest.mark.asyncio
async def test_queued_ingest_ignores_task_metadata_commit_failure(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "source.html"
    source.write_text("<html>ok</html>", encoding="utf-8")
    db_document = SimpleNamespace(doc_metadata={}, file_path="minio://documents/documents/t/d/source.html")

    async def _queued(**_kwargs):  # noqa: ANN003, ANN202
        return "task-1"

    class _FailingDB:
        def commit(self) -> None:
            raise RuntimeError("metadata commit failed")

        def rollback(self) -> None:
            return None

    monkeypatch.setattr(documents_module, "enqueue_document_processing", _queued, raising=True)

    keep_local = await documents_module._schedule_document_processing(
        db=_FailingDB(),
        background_tasks=BackgroundTasks(),
        tenant_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        file_path=source,
        requested_by="account-1",
        pipeline_hash="pipeline-hash",
        parser_backend="auto",
        chunk_strategy="langchain_recursive",
        db_document=db_document,
    )

    assert keep_local is False


@pytest.mark.asyncio
async def test_schedule_document_processing_falls_back_when_enqueue_fails(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "source.html"
    source.write_text("<html>ok</html>", encoding="utf-8")
    processed: list[Path] = []
    background_tasks = BackgroundTasks()
    db_document = SimpleNamespace(doc_metadata={}, file_path="minio://documents/documents/t/d/source.html")

    async def _fail_enqueue(**_kwargs):  # noqa: ANN003, ANN202
        raise RuntimeError("redis unavailable")

    async def _process(file_path, *_args):  # noqa: ANN001, ANN002, ANN202
        processed.append(file_path)

    monkeypatch.setattr(documents_module.settings, "TASK_QUEUE_ENABLED", False, raising=False)
    monkeypatch.setattr(documents_module, "enqueue_document_processing", _fail_enqueue, raising=True)
    monkeypatch.setattr(documents_module, "run_document_processing_limited", _process, raising=True)

    keep_local = await documents_module._schedule_document_processing(
        db=_DB(),
        background_tasks=background_tasks,
        tenant_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        file_path=source,
        requested_by="account-1",
        pipeline_hash="pipeline-hash",
        parser_backend="auto",
        chunk_strategy="langchain_recursive",
        db_document=db_document,
    )

    assert keep_local is True
    await background_tasks()
    assert processed == [source]
    assert not source.exists()


@pytest.mark.asyncio
async def test_schedule_document_processing_fails_closed_when_queue_handoff_fails(
    monkeypatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.html"
    source.write_text("<html>ok</html>", encoding="utf-8")
    db_document = SimpleNamespace(
        status="pending",
        current_stage="queued",
        error_message=None,
        doc_metadata={},
        file_path="minio://documents/documents/t/d/source.html",
    )
    commits: list[str] = []

    async def _fail_enqueue(**_kwargs):  # noqa: ANN003, ANN202
        raise RuntimeError("redis unavailable")

    class _FailingQueueDB:
        def commit(self) -> None:
            commits.append("commit")

        def refresh(self, _obj) -> None:  # noqa: ANN001
            return None

        def rollback(self) -> None:
            return None

    monkeypatch.setattr(documents_module.settings, "TASK_QUEUE_ENABLED", True, raising=False)
    monkeypatch.setattr(documents_module, "enqueue_document_processing", _fail_enqueue, raising=True)

    with pytest.raises(HTTPException) as exc_info:
        await documents_module._schedule_document_processing(
            db=_FailingQueueDB(),
            background_tasks=BackgroundTasks(),
            tenant_id=uuid.uuid4(),
            document_id=uuid.uuid4(),
            file_path=source,
            requested_by="account-1",
            pipeline_hash="pipeline-hash",
            parser_backend="auto",
            chunk_strategy="langchain_recursive",
            db_document=db_document,
        )

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == documents_module.DOCUMENT_PROCESSING_QUEUE_UNAVAILABLE_DETAIL
    assert commits == ["commit"]
    assert db_document.status == "failed"
    assert db_document.current_stage == "failed"
    assert db_document.error_message == "document_processing_schedule_failed"
    assert source.exists()


def _dataset(dataset_id: uuid.UUID) -> SimpleNamespace:
    return SimpleNamespace(id=dataset_id, dataset_metadata={})


def _prepared() -> documents_module.PreparedDocumentIngestion:
    return documents_module.PreparedDocumentIngestion(
        policy=documents_module.ResolvedDocumentIngestionPolicy(
            parser_backend_choice="auto",
            chunk_strategy_choice="langchain_recursive",
            pipeline_options=PipelineOptions(),
            ingestion_meta=None,
        ),
        pipeline=documents_module.ResolvedDocumentPipeline(
            parser_backend="auto",
            chunk_strategy="langchain_recursive",
        ),
    )


@pytest.mark.asyncio
async def test_store_ingested_source_uses_minio_when_enabled(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "source.html"
    source.write_text("<html>ok</html>", encoding="utf-8")
    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    document_id = uuid.uuid4()
    calls: list[dict] = []

    monkeypatch.setattr(documents_module.settings, "MINIO_ENABLED", True, raising=False)
    monkeypatch.setattr(documents_module.settings, "MINIO_DOCUMENTS_ENABLED", True, raising=False)

    def _upload(**kwargs):  # noqa: ANN003, ANN202
        calls.append(kwargs)
        return "minio://documents/documents/t/d/source.html"

    monkeypatch.setattr(documents_module.minio_service, "upload_document_file", _upload, raising=True)

    stored_path = await documents_module._store_ingested_source(
        file_path=source,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        document_id=document_id,
        extension=".html",
        content_type="text/html",
    )

    assert stored_path == "minio://documents/documents/t/d/source.html"
    assert calls == [
        {
            "file_path": source,
            "tenant_id": str(tenant_id),
            "dataset_id": str(dataset_id),
            "document_id": str(document_id),
            "extension": ".html",
            "content_type": "text/html",
        }
    ]
    assert source.exists()


@pytest.mark.asyncio
async def test_store_ingested_source_removes_temp_when_minio_upload_fails(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "source.html"
    source.write_text("<html>ok</html>", encoding="utf-8")

    monkeypatch.setattr(documents_module.settings, "MINIO_ENABLED", True, raising=False)
    monkeypatch.setattr(documents_module.settings, "MINIO_DOCUMENTS_ENABLED", True, raising=False)
    monkeypatch.setattr(
        documents_module.minio_service,
        "upload_document_file",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("minio unavailable")),
        raising=True,
    )

    with pytest.raises(RuntimeError, match="minio unavailable"):
        await documents_module._store_ingested_source(
            file_path=source,
            tenant_id=uuid.uuid4(),
            dataset_id=uuid.uuid4(),
            document_id=uuid.uuid4(),
            extension=".html",
            content_type="text/html",
        )

    assert not source.exists()


@pytest.mark.asyncio
async def test_ingest_url_request_persists_minio_uri_and_cleans_temp_after_queue(monkeypatch, tmp_path: Path) -> None:
    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    upload_calls: list[dict] = []

    monkeypatch.setattr(documents_module.settings, "URL_INGEST_ENABLED", True, raising=False)
    monkeypatch.setattr(documents_module.settings, "MINIO_ENABLED", True, raising=False)
    monkeypatch.setattr(documents_module.settings, "MINIO_DOCUMENTS_ENABLED", True, raising=False)
    monkeypatch.setattr(documents_module.settings, "UPLOAD_DIR", str(tmp_path), raising=False)

    async def _validate(url: str) -> str:
        return url

    async def _download(url: str, destination: Path, **_kwargs):  # noqa: ANN202
        payload = b"hello from url"
        destination.write_bytes(payload)
        return DownloadedURL(size_bytes=len(payload), content_type="text/plain", final_url=url)

    async def _queued(**_kwargs):  # noqa: ANN003, ANN202
        return "task-123"

    def _upload(**kwargs):  # noqa: ANN003, ANN202
        upload_calls.append(kwargs)
        return f"minio://documents/documents/{kwargs['tenant_id']}/{kwargs['dataset_id']}/{kwargs['document_id']}.txt"

    monkeypatch.setattr(documents_module, "validate_url_for_ingest", _validate, raising=True)
    monkeypatch.setattr(documents_module, "download_url_to_path", _download, raising=True)
    monkeypatch.setattr(documents_module, "_resolve_writable_dataset", lambda *_args, **_kwargs: _dataset(dataset_id), raising=True)
    monkeypatch.setattr(documents_module, "_prepare_document_ingestion", lambda **_kwargs: _prepared(), raising=True)
    monkeypatch.setattr(documents_module, "_create_url_ingestion_run", lambda **_kwargs: None, raising=True)
    monkeypatch.setattr(documents_module, "enqueue_document_processing", _queued, raising=True)
    monkeypatch.setattr(documents_module.minio_service, "upload_document_file", _upload, raising=True)

    body = documents_module.UrlUploadRequest(
        url="https://example.com/doc.txt",
        dataset_id=dataset_id,
        filename="doc.txt",
    )
    db = _DB()

    document = await documents_module._ingest_url_upload_request(
        background_tasks=BackgroundTasks(),
        body=body,
        tenant_id=tenant_id,
        account_id="account-1",
        db=db,
    )

    assert document.file_path == f"minio://documents/documents/{tenant_id}/{dataset_id}/{document.id}.txt"
    assert document.doc_metadata["task_id"] == "task-123"
    assert upload_calls and upload_calls[0]["dataset_id"] == str(dataset_id)
    assert not any((tmp_path / str(tenant_id)).glob("*.txt"))


@pytest.mark.asyncio
async def test_ingest_local_html_request_persists_minio_uri_and_cleans_temp_after_queue(monkeypatch, tmp_path: Path) -> None:
    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()

    monkeypatch.setattr(documents_module.settings, "URL_INGEST_ENABLED", True, raising=False)
    monkeypatch.setattr(documents_module.settings, "MINIO_ENABLED", True, raising=False)
    monkeypatch.setattr(documents_module.settings, "MINIO_DOCUMENTS_ENABLED", True, raising=False)
    monkeypatch.setattr(documents_module.settings, "UPLOAD_DIR", str(tmp_path), raising=False)

    async def _queued(**_kwargs):  # noqa: ANN003, ANN202
        return "task-456"

    monkeypatch.setattr(documents_module, "_resolve_writable_dataset", lambda *_args, **_kwargs: _dataset(dataset_id), raising=True)
    monkeypatch.setattr(documents_module, "_prepare_document_ingestion", lambda **_kwargs: _prepared(), raising=True)
    monkeypatch.setattr(documents_module, "_create_local_html_ingestion_run", lambda **_kwargs: None, raising=True)
    monkeypatch.setattr(documents_module, "enqueue_document_processing", _queued, raising=True)
    monkeypatch.setattr(
        documents_module.minio_service,
        "upload_document_file",
        lambda **kwargs: f"minio://documents/documents/{kwargs['tenant_id']}/{kwargs['dataset_id']}/{kwargs['document_id']}.html",
        raising=True,
    )

    body = documents_module.LocalHtmlIngestRequest(
        html="<html><body>Hello</body></html>",
        source_url="https://example.com/page",
        dataset_id=dataset_id,
        filename="page.html",
    )
    db = _DB()

    document = await documents_module._ingest_local_html_request(
        background_tasks=BackgroundTasks(),
        body=body,
        tenant_id=tenant_id,
        account_id="account-1",
        db=db,
    )

    assert document.file_path == f"minio://documents/documents/{tenant_id}/{dataset_id}/{document.id}.html"
    assert document.doc_metadata["task_id"] == "task-456"
    assert not any((tmp_path / str(tenant_id)).glob("*.html"))


@pytest.mark.asyncio
async def test_persist_and_process_ingested_document_add_failure_deletes_unpersisted_object_and_temp(
    monkeypatch, tmp_path: Path
) -> None:
    source = tmp_path / "source.html"
    source.write_text("<html>ok</html>", encoding="utf-8")
    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    document_id = uuid.uuid4()
    deleted: list[str] = []

    class _FailingDB:
        def add(self, _obj) -> None:  # noqa: ANN001
            raise RuntimeError("add failed")

        def rollback(self) -> None:
            return None

    monkeypatch.setattr(
        documents_module.minio_service,
        "delete_object",
        lambda *, object_name: deleted.append(object_name),
        raising=True,
    )

    with pytest.raises(RuntimeError, match="add failed"):
        await documents_module._persist_and_process_ingested_document(
            db=_FailingDB(),
            background_tasks=BackgroundTasks(),
            tenant_id=tenant_id,
            account_id="account-1",
            dataset=_dataset(dataset_id),
            file_id=document_id,
            filename="page.html",
            file_ext=".html",
            file_size=source.stat().st_size,
            file_path=f"minio://documents/documents/{tenant_id}/{dataset_id}/{document_id}.html",
            processing_file_path=source,
            source_ref="https://example.com/page",
            doc_metadata={},
            pipeline_hash="pipeline-hash",
            pipeline=documents_module.ResolvedDocumentPipeline(
                parser_backend="auto",
                chunk_strategy="langchain_recursive",
            ),
            ingestion_run_id=None,
        )

    assert deleted == [f"documents/{tenant_id}/{dataset_id}/{document_id}.html"]
    assert not source.exists()


@pytest.mark.asyncio
async def test_persist_and_process_ingested_document_commit_failure_keeps_object_when_row_exists(
    monkeypatch, tmp_path: Path
) -> None:
    source = tmp_path / "source.html"
    source.write_text("<html>ok</html>", encoding="utf-8")
    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    document_id = uuid.uuid4()
    deleted: list[str] = []

    class _FailingDB:
        def add(self, _obj) -> None:  # noqa: ANN001
            return None

        def commit(self) -> None:
            raise RuntimeError("commit failed")

        def rollback(self) -> None:
            return None

    monkeypatch.setattr(
        documents_module.minio_service,
        "delete_object",
        lambda *, object_name: deleted.append(object_name),
        raising=True,
    )
    monkeypatch.setattr(
        documents_module,
        "SessionLocal",
        lambda: SimpleNamespace(get=lambda *_args, **_kwargs: object(), close=lambda: None),
        raising=True,
    )

    with pytest.raises(RuntimeError, match="commit failed"):
        await documents_module._persist_and_process_ingested_document(
            db=_FailingDB(),
            background_tasks=BackgroundTasks(),
            tenant_id=tenant_id,
            account_id="account-1",
            dataset=_dataset(dataset_id),
            file_id=document_id,
            filename="page.html",
            file_ext=".html",
            file_size=source.stat().st_size,
            file_path=f"minio://documents/documents/{tenant_id}/{dataset_id}/{document_id}.html",
            processing_file_path=source,
            source_ref="https://example.com/page",
            doc_metadata={},
            pipeline_hash="pipeline-hash",
            pipeline=documents_module.ResolvedDocumentPipeline(
                parser_backend="auto",
                chunk_strategy="langchain_recursive",
            ),
            ingestion_run_id=None,
        )

    assert deleted == []
    assert not source.exists()


@pytest.mark.asyncio
async def test_persist_and_process_ingested_document_commit_failure_deletes_object_when_row_missing(
    monkeypatch, tmp_path: Path
) -> None:
    source = tmp_path / "source.html"
    source.write_text("<html>ok</html>", encoding="utf-8")
    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    document_id = uuid.uuid4()
    deleted: list[str] = []

    class _FailingDB:
        def add(self, _obj) -> None:  # noqa: ANN001
            return None

        def commit(self) -> None:
            raise RuntimeError("commit failed")

        def rollback(self) -> None:
            return None

    monkeypatch.setattr(
        documents_module.minio_service,
        "delete_object",
        lambda *, object_name: deleted.append(object_name),
        raising=True,
    )
    monkeypatch.setattr(
        documents_module,
        "SessionLocal",
        lambda: SimpleNamespace(get=lambda *_args, **_kwargs: None, close=lambda: None),
        raising=True,
    )

    with pytest.raises(RuntimeError, match="commit failed"):
        await documents_module._persist_and_process_ingested_document(
            db=_FailingDB(),
            background_tasks=BackgroundTasks(),
            tenant_id=tenant_id,
            account_id="account-1",
            dataset=_dataset(dataset_id),
            file_id=document_id,
            filename="page.html",
            file_ext=".html",
            file_size=source.stat().st_size,
            file_path=f"minio://documents/documents/{tenant_id}/{dataset_id}/{document_id}.html",
            processing_file_path=source,
            source_ref="https://example.com/page",
            doc_metadata={},
            pipeline_hash="pipeline-hash",
            pipeline=documents_module.ResolvedDocumentPipeline(
                parser_backend="auto",
                chunk_strategy="langchain_recursive",
            ),
            ingestion_run_id=None,
        )

    assert deleted == [f"documents/{tenant_id}/{dataset_id}/{document_id}.html"]
    assert not source.exists()


@pytest.mark.asyncio
async def test_persist_and_process_ingested_document_commit_failure_keeps_local_source_when_row_exists(
    monkeypatch, tmp_path: Path
) -> None:
    source = tmp_path / "source.html"
    source.write_text("<html>ok</html>", encoding="utf-8")
    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    document_id = uuid.uuid4()

    class _FailingDB:
        def add(self, _obj) -> None:  # noqa: ANN001
            return None

        def commit(self) -> None:
            raise RuntimeError("commit failed")

        def rollback(self) -> None:
            return None

    monkeypatch.setattr(
        documents_module,
        "SessionLocal",
        lambda: SimpleNamespace(get=lambda *_args, **_kwargs: object(), close=lambda: None),
        raising=True,
    )

    with pytest.raises(RuntimeError, match="commit failed"):
        await documents_module._persist_and_process_ingested_document(
            db=_FailingDB(),
            background_tasks=BackgroundTasks(),
            tenant_id=tenant_id,
            account_id="account-1",
            dataset=_dataset(dataset_id),
            file_id=document_id,
            filename="page.html",
            file_ext=".html",
            file_size=source.stat().st_size,
            file_path=source,
            processing_file_path=source,
            source_ref="https://example.com/page",
            doc_metadata={},
            pipeline_hash="pipeline-hash",
            pipeline=documents_module.ResolvedDocumentPipeline(
                parser_backend="auto",
                chunk_strategy="langchain_recursive",
            ),
            ingestion_run_id=None,
        )

    assert source.exists()


@pytest.mark.asyncio
async def test_persist_and_process_ingested_document_commit_failure_keeps_local_source_when_row_existence_unknown(
    monkeypatch, tmp_path: Path
) -> None:
    source = tmp_path / "source.html"
    source.write_text("<html>ok</html>", encoding="utf-8")
    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    document_id = uuid.uuid4()

    class _FailingDB:
        def add(self, _obj) -> None:  # noqa: ANN001
            return None

        def commit(self) -> None:
            raise RuntimeError("commit failed")

        def rollback(self) -> None:
            return None

    monkeypatch.setattr(
        documents_module,
        "SessionLocal",
        lambda: (_ for _ in ()).throw(RuntimeError("session unavailable")),
        raising=True,
    )

    with pytest.raises(RuntimeError, match="commit failed"):
        await documents_module._persist_and_process_ingested_document(
            db=_FailingDB(),
            background_tasks=BackgroundTasks(),
            tenant_id=tenant_id,
            account_id="account-1",
            dataset=_dataset(dataset_id),
            file_id=document_id,
            filename="page.html",
            file_ext=".html",
            file_size=source.stat().st_size,
            file_path=source,
            processing_file_path=source,
            source_ref="https://example.com/page",
            doc_metadata={},
            pipeline_hash="pipeline-hash",
            pipeline=documents_module.ResolvedDocumentPipeline(
                parser_backend="auto",
                chunk_strategy="langchain_recursive",
            ),
            ingestion_run_id=None,
        )

    assert source.exists()

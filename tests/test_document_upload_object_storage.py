import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import BackgroundTasks

from app.api.v1 import documents as documents_module

document_upload = documents_module.document_upload


@pytest.mark.asyncio
async def test_store_document_source_uses_minio_when_document_storage_enabled(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "source.txt"
    source.write_text("hello", encoding="utf-8")
    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    document_id = uuid.uuid4()
    calls: list[dict] = []

    monkeypatch.setattr(document_upload.settings, "MINIO_ENABLED", True, raising=False)
    monkeypatch.setattr(document_upload.settings, "MINIO_DOCUMENTS_ENABLED", True, raising=False)

    def _upload(**kwargs):  # noqa: ANN003, ANN202
        calls.append(kwargs)
        return "minio://documents/documents/t/d/source.txt"

    monkeypatch.setattr(document_upload.minio_service, "upload_document_file", _upload, raising=True)

    stored_path = await document_upload._store_document_source(
        file_path=source,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        document_id=document_id,
        extension=".txt",
        content_type="text/plain",
    )

    assert stored_path == "minio://documents/documents/t/d/source.txt"
    assert calls == [
        {
            "file_path": source,
            "tenant_id": str(tenant_id),
            "dataset_id": str(dataset_id),
            "document_id": str(document_id),
            "extension": ".txt",
            "content_type": "text/plain",
        }
    ]
    assert source.exists()


@pytest.mark.asyncio
async def test_store_document_source_removes_temp_when_minio_upload_fails(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "source.txt"
    source.write_text("hello", encoding="utf-8")
    monkeypatch.setattr(document_upload.settings, "MINIO_ENABLED", True, raising=False)
    monkeypatch.setattr(document_upload.settings, "MINIO_DOCUMENTS_ENABLED", True, raising=False)

    def _fail_upload(**_kwargs):  # noqa: ANN003, ANN202
        raise RuntimeError("minio unavailable")

    monkeypatch.setattr(document_upload.minio_service, "upload_document_file", _fail_upload, raising=True)

    with pytest.raises(RuntimeError, match="minio unavailable"):
        await document_upload._store_document_source(
            file_path=source,
            tenant_id=uuid.uuid4(),
            dataset_id=uuid.uuid4(),
            document_id=uuid.uuid4(),
            extension=".txt",
            content_type="text/plain",
        )
    assert not source.exists()


@pytest.mark.asyncio
async def test_schedule_document_processing_cleans_object_temp_after_fallback_failure(
    monkeypatch, tmp_path: Path
) -> None:
    from app.api.v1 import documents as documents_module

    source = tmp_path / "source.txt"
    source.write_text("hello", encoding="utf-8")
    tenant_id = uuid.uuid4()
    document_id = uuid.uuid4()
    background_tasks = BackgroundTasks()
    db_document = SimpleNamespace(doc_metadata={}, file_path="minio://documents/documents/t/d/source.txt")

    async def _no_queue(**_kwargs):  # noqa: ANN003, ANN202
        return None

    async def _fail_processing(*_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
        raise RuntimeError("processing failed")

    monkeypatch.setattr(documents_module, "enqueue_document_processing", _no_queue, raising=True)
    monkeypatch.setattr(documents_module, "run_document_processing_limited", _fail_processing, raising=True)

    keep_local_file = await document_upload._schedule_document_processing(
        background_tasks=background_tasks,
        file_path=source,
        document_id=document_id,
        tenant_id=tenant_id,
        account_id="account-1",
        pipeline_hash="pipeline-hash",
        parser_backend="auto",
        chunk_strategy="langchain_recursive",
        db=SimpleNamespace(),
        db_document=db_document,
    )

    assert keep_local_file is True
    with pytest.raises(RuntimeError, match="processing failed"):
        await background_tasks()
    assert not source.exists()


@pytest.mark.asyncio
async def test_schedule_document_processing_returns_object_temp_to_request_after_queueing(
    monkeypatch, tmp_path: Path
) -> None:
    from app.api.v1 import documents as documents_module

    source = tmp_path / "source.txt"
    source.write_text("hello", encoding="utf-8")
    db_document = SimpleNamespace(doc_metadata={}, file_path="minio://documents/documents/t/d/source.txt")

    async def _queued(**_kwargs):  # noqa: ANN003, ANN202
        return "task-1"

    class _DB:
        def commit(self) -> None:
            return None

        def refresh(self, _document) -> None:  # noqa: ANN001
            return None

    monkeypatch.setattr(documents_module, "enqueue_document_processing", _queued, raising=True)

    keep_local_file = await document_upload._schedule_document_processing(
        background_tasks=BackgroundTasks(),
        file_path=source,
        document_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        account_id="account-1",
        pipeline_hash="pipeline-hash",
        parser_backend="auto",
        chunk_strategy="langchain_recursive",
        db=_DB(),
        db_document=db_document,
    )

    assert keep_local_file is False
    assert db_document.doc_metadata["task_id"] == "task-1"
    assert source.exists()


@pytest.mark.asyncio
async def test_schedule_document_processing_falls_back_when_enqueue_fails(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "source.txt"
    source.write_text("hello", encoding="utf-8")
    processed: list[Path] = []
    background_tasks = BackgroundTasks()
    db_document = SimpleNamespace(doc_metadata={}, file_path="minio://documents/documents/t/d/source.txt")

    async def _fail_enqueue(**_kwargs):  # noqa: ANN003, ANN202
        raise RuntimeError("redis unavailable")

    async def _process(file_path, *_args):  # noqa: ANN001, ANN002, ANN202
        processed.append(file_path)

    monkeypatch.setattr(documents_module, "enqueue_document_processing", _fail_enqueue, raising=True)
    monkeypatch.setattr(documents_module, "run_document_processing_limited", _process, raising=True)

    keep_local_file = await document_upload._schedule_document_processing(
        background_tasks=background_tasks,
        file_path=source,
        document_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        account_id="account-1",
        pipeline_hash="pipeline-hash",
        parser_backend="auto",
        chunk_strategy="langchain_recursive",
        db=SimpleNamespace(),
        db_document=db_document,
    )

    assert keep_local_file is True
    assert source.exists()
    await background_tasks()
    assert processed == [source]
    assert not source.exists()


@pytest.mark.asyncio
async def test_schedule_document_processing_ignores_task_metadata_commit_failure(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "source.txt"
    source.write_text("hello", encoding="utf-8")
    rollbacks: list[bool] = []
    db_document = SimpleNamespace(doc_metadata={}, file_path="minio://documents/documents/t/d/source.txt")

    async def _queued(**_kwargs):  # noqa: ANN003, ANN202
        return "task-1"

    class _DB:
        def commit(self) -> None:
            raise RuntimeError("metadata commit failed")

        def rollback(self) -> None:
            rollbacks.append(True)

    monkeypatch.setattr(documents_module, "enqueue_document_processing", _queued, raising=True)

    keep_local_file = await document_upload._schedule_document_processing(
        background_tasks=BackgroundTasks(),
        file_path=source,
        document_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        account_id="account-1",
        pipeline_hash="pipeline-hash",
        parser_backend="auto",
        chunk_strategy="langchain_recursive",
        db=_DB(),
        db_document=db_document,
    )

    assert keep_local_file is False
    assert rollbacks == [True]
    assert source.exists()


@pytest.mark.asyncio
async def test_cleanup_unpersisted_object_deletes_minio_object(monkeypatch) -> None:
    deleted: list[str] = []
    monkeypatch.setattr(
        document_upload.minio_service,
        "delete_object",
        lambda *, object_name: deleted.append(object_name),
        raising=True,
    )

    await document_upload._cleanup_unpersisted_source("minio://documents/documents/t/d/source.txt")

    assert deleted == ["documents/t/d/source.txt"]


@pytest.mark.asyncio
async def test_persist_commit_failure_keeps_uploaded_object(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "source.txt"
    source.write_text("hello", encoding="utf-8")
    deleted: list[str] = []
    rollbacks: list[bool] = []
    db_document = SimpleNamespace(file_path="minio://documents/documents/t/d/source.txt")

    class _FailingDB:
        def add(self, _document) -> None:  # noqa: ANN001
            return None

        def commit(self) -> None:
            raise RuntimeError("commit failed")

        def rollback(self) -> None:
            rollbacks.append(True)

    monkeypatch.setattr(
        document_upload.minio_service,
        "delete_object",
        lambda *, object_name: deleted.append(object_name),
        raising=True,
    )

    with pytest.raises(RuntimeError, match="commit failed"):
        await document_upload._persist_uploaded_document(_FailingDB(), db_document, file_path=source)

    assert rollbacks == [True]
    assert deleted == []
    assert source.exists()


@pytest.mark.asyncio
async def test_persist_add_failure_deletes_definitely_unpersisted_object(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "source.txt"
    source.write_text("hello", encoding="utf-8")
    deleted: list[str] = []
    db_document = SimpleNamespace(file_path="minio://documents/documents/t/d/source.txt")

    class _DB:
        def add(self, _document) -> None:  # noqa: ANN001
            raise RuntimeError("add failed")

        def rollback(self) -> None:
            return None

    monkeypatch.setattr(
        document_upload.minio_service,
        "delete_object",
        lambda *, object_name: deleted.append(object_name),
        raising=True,
    )

    with pytest.raises(RuntimeError, match="add failed"):
        await document_upload._persist_uploaded_document(_DB(), db_document, file_path=source)

    assert deleted == ["documents/t/d/source.txt"]
    assert not source.exists()


@pytest.mark.asyncio
async def test_persist_refresh_failure_does_not_fail_committed_upload(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "source.txt"
    source.write_text("hello", encoding="utf-8")
    deleted: list[str] = []
    db_document = SimpleNamespace(file_path="minio://documents/documents/t/d/source.txt")

    class _DB:
        def add(self, _document) -> None:  # noqa: ANN001
            return None

        def commit(self) -> None:
            return None

        def refresh(self, _document) -> None:  # noqa: ANN001
            raise RuntimeError("refresh failed")

    monkeypatch.setattr(
        document_upload.minio_service,
        "delete_object",
        lambda *, object_name: deleted.append(object_name),
        raising=True,
    )

    await document_upload._persist_uploaded_document(_DB(), db_document, file_path=source)

    assert deleted == []
    assert source.exists()


@pytest.mark.asyncio
async def test_upload_document_finally_cleans_unowned_temp(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "source.txt"
    source.write_text("hello", encoding="utf-8")

    async def _fail_impl(*_args, file_lease, **_kwargs):  # noqa: ANN002, ANN003, ANN202
        file_lease.acquire(source)
        raise RuntimeError("validation failed")

    monkeypatch.setattr(document_upload, "_upload_document_impl", _fail_impl, raising=True)

    with pytest.raises(RuntimeError, match="validation failed"):
        await document_upload.upload_document(
            BackgroundTasks(),
            SimpleNamespace(filename="source.txt"),
            SimpleNamespace(),
            SimpleNamespace(),
            tenant_id=uuid.uuid4(),
            account_id="account-1",
            db=SimpleNamespace(),
        )

    assert not source.exists()


@pytest.mark.asyncio
async def test_upload_document_finally_preserves_transferred_file(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "source.txt"
    source.write_text("hello", encoding="utf-8")

    async def _transfer_impl(*_args, file_lease, **_kwargs):  # noqa: ANN002, ANN003, ANN202
        file_lease.acquire(source)
        file_lease.transfer()
        return "scheduled"

    monkeypatch.setattr(document_upload, "_upload_document_impl", _transfer_impl, raising=True)

    result = await document_upload.upload_document(
        BackgroundTasks(),
        SimpleNamespace(filename="source.txt"),
        SimpleNamespace(),
        SimpleNamespace(),
        tenant_id=uuid.uuid4(),
        account_id="account-1",
        db=SimpleNamespace(),
    )

    assert result == "scheduled"
    assert source.exists()


def test_document_upload_path_uses_temp_only_for_object_storage(monkeypatch, tmp_path: Path) -> None:
    tenant_id = uuid.uuid4()
    document_id = uuid.uuid4()
    monkeypatch.setattr(document_upload.settings, "UPLOAD_DIR", str(tmp_path), raising=False)

    monkeypatch.setattr(document_upload.settings, "MINIO_ENABLED", False, raising=False)
    monkeypatch.setattr(document_upload.settings, "MINIO_DOCUMENTS_ENABLED", True, raising=False)
    local_path = document_upload._document_upload_path(tenant_id, document_id, ".txt")
    assert local_path == tmp_path / str(tenant_id) / f"{document_id}.txt"

    monkeypatch.setattr(document_upload.settings, "MINIO_ENABLED", True, raising=False)
    object_temp_path = document_upload._document_upload_path(tenant_id, document_id, ".txt")
    assert object_temp_path == tmp_path / str(tenant_id) / ".tmp" / f"{document_id}.txt"

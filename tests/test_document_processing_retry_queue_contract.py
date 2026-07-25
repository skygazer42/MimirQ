import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import BackgroundTasks, HTTPException

from app.api.v1 import document_processing


class _Query:
    def __init__(self, document, *, model, deletes: list[object]) -> None:  # noqa: ANN001
        self._document = document
        self._model = model
        self._deletes = deletes

    def filter(self, *_args, **_kwargs):  # noqa: ANN002, ANN003
        return self

    def first(self):  # noqa: ANN201
        return self._document

    def delete(self, **_kwargs) -> int:  # noqa: ANN003
        self._deletes.append(self._model)
        return 0

    def all(self) -> list[tuple]:
        return []

    def limit(self, _value):  # noqa: ANN001
        return self


class _DB:
    def __init__(self, document) -> None:  # noqa: ANN001
        self.document = document
        self.commits = 0
        self.rollbacks = 0
        self.deletes: list[object] = []

    def query(self, model):  # noqa: ANN001, ANN201
        return _Query(self.document, model=model, deletes=self.deletes)

    def commit(self) -> None:
        self.commits += 1

    def refresh(self, _obj) -> None:  # noqa: ANN001
        return None

    def rollback(self) -> None:
        self.rollbacks += 1


@pytest.mark.asyncio
async def test_retry_document_processing_fails_closed_when_queue_handoff_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    documents_module = document_processing._documents_module()
    source = tmp_path / "retry.txt"
    source.write_text("hello", encoding="utf-8")
    document = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        dataset_id=uuid.uuid4(),
        file_path=str(source),
        file_type="txt",
        filename="retry.txt",
        status="failed",
        processing_progress=100,
        current_stage="failed",
        failed_stage="parse",
        error_code="boom",
        next_retry_at=None,
        error_message="old-error",
        chunk_count=12,
        total_characters=34,
        doc_metadata={
            "parser_backend": "auto",
            "chunk_strategy": "langchain_recursive",
            "pipeline_hash": "stable-pipeline",
            "active_pipeline_hash": "stable-pipeline",
            "active_pipeline_ready": True,
            "ingest_checkpoint": {"version": "1", "stage": "parsed"},
            "parsed_content_persisted": {"cleaned": {"text": "old parsed text"}},
            "task_id": "old-task",
            "kg_task_id": "old-kg-task",
        },
    )
    db = _DB(document)
    cleanup_calls: list[str] = []

    async def _no_task(**_kwargs):  # noqa: ANN003, ANN202
        return None

    monkeypatch.setattr(documents_module.settings, "TASK_QUEUE_ENABLED", True, raising=False)
    monkeypatch.setattr(documents_module.DatasetService, "ensure_member", lambda *_args, **_kwargs: None, raising=True)
    monkeypatch.setattr(
        documents_module.DatasetService,
        "get_dataset",
        lambda *_args, **_kwargs: SimpleNamespace(id=document.dataset_id),
        raising=True,
    )
    monkeypatch.setattr(
        documents_module.DatasetService,
        "assert_dataset_writable",
        lambda *_args, **_kwargs: None,
        raising=True,
    )
    monkeypatch.setattr(
        documents_module,
        "Indexer",
        lambda _db: SimpleNamespace(
            delete_chunk_indexes=lambda **_kwargs: cleanup_calls.append("chunks"),
            delete_event_indexes=lambda **_kwargs: cleanup_calls.append("events"),
        ),
        raising=False,
    )
    monkeypatch.setattr(documents_module, "_compute_pipeline_hash", lambda _meta: "stable-pipeline", raising=True)
    monkeypatch.setattr(documents_module, "enqueue_document_processing", _no_task, raising=True)
    monkeypatch.setattr(documents_module, "_task_queue_required", lambda: True, raising=True)

    with pytest.raises(HTTPException) as exc_info:
        await document_processing.retry_document_processing(
            document_id=document.id,
            background_tasks=BackgroundTasks(),
            force=True,
            tenant_id=document.tenant_id,
            account_id="acct-1",
            db=db,
        )

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == documents_module.DOCUMENT_PROCESSING_QUEUE_UNAVAILABLE_DETAIL
    assert document.status == "failed"
    assert document.current_stage == "failed"
    assert document.error_message == "document_processing_schedule_failed"
    assert document.doc_metadata.get("task_id") is None
    assert document.doc_metadata.get("kg_task_id") is None
    assert document.doc_metadata.get("ingest_checkpoint") == {"version": "1", "stage": "parsed"}
    assert document.doc_metadata.get("parsed_content_persisted") == {"cleaned": {"text": "old parsed text"}}
    assert cleanup_calls == []
    assert db.deletes == []
    assert document.chunk_count == 12
    assert document.total_characters == 34
    assert db.commits >= 2


@pytest.mark.asyncio
async def test_retry_document_processing_local_fallback_preserves_then_consumes_retry_cleanup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app.parsing.processors import processor

    documents_module = document_processing._documents_module()
    source = tmp_path / "retry-local.txt"
    source.write_text("hello", encoding="utf-8")
    document = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        dataset_id=uuid.uuid4(),
        file_path=str(source),
        file_type="txt",
        filename="retry-local.txt",
        status="failed",
        processing_progress=100,
        current_stage="failed",
        failed_stage="parse",
        error_code="boom",
        next_retry_at=None,
        error_message="old-error",
        chunk_count=12,
        total_characters=34,
        doc_metadata={
            "parser_backend": "auto",
            "chunk_strategy": "langchain_recursive",
            "pipeline_hash": "stable-pipeline",
            "active_pipeline_hash": "stable-pipeline",
            "active_pipeline_ready": True,
            "ingest_checkpoint": {"version": "1", "stage": "parsed"},
            "parsed_content_persisted": {"cleaned": {"text": "old parsed text"}},
            "img_ids": ["old-image"],
        },
    )
    db = _DB(document)
    background_tasks = BackgroundTasks()
    cleanup_calls: list[str] = []
    processing_calls: list[dict[str, object]] = []

    class _Indexer:
        def __init__(self, _db) -> None:  # noqa: ANN001
            pass

        def delete_chunk_indexes(self, **_kwargs) -> None:  # noqa: ANN003
            cleanup_calls.append("chunks")

        def delete_event_indexes(self, **_kwargs) -> None:  # noqa: ANN003
            cleanup_calls.append("events")

    async def _process(file_path, document_id, tenant_id, parser_backend, chunk_strategy):  # noqa: ANN001, ANN202
        processing_calls.append(
            {
                "file_path": file_path,
                "document_id": document_id,
                "tenant_id": tenant_id,
                "parser_backend": parser_backend,
                "chunk_strategy": chunk_strategy,
                "retry_cleanup_before": dict(document.doc_metadata.get("retry_cleanup") or {}),
            }
        )
        processor.DocumentProcessorService()._apply_pending_retry_cleanup(
            db,
            db_document=document,
            tenant_id=tenant_id,
            document_id=document_id,
        )

    async def _no_task(**_kwargs):  # noqa: ANN003, ANN202
        return None

    monkeypatch.setattr(documents_module.settings, "TASK_QUEUE_ENABLED", False, raising=False)
    monkeypatch.setattr(documents_module.DatasetService, "ensure_member", lambda *_args, **_kwargs: None, raising=True)
    monkeypatch.setattr(
        documents_module.DatasetService,
        "get_dataset",
        lambda *_args, **_kwargs: SimpleNamespace(id=document.dataset_id),
        raising=True,
    )
    monkeypatch.setattr(
        documents_module.DatasetService,
        "assert_dataset_writable",
        lambda *_args, **_kwargs: None,
        raising=True,
    )
    monkeypatch.setattr(documents_module, "_compute_pipeline_hash", lambda _meta: "stable-pipeline", raising=True)
    monkeypatch.setattr(documents_module, "enqueue_document_processing", _no_task, raising=True)
    monkeypatch.setattr(documents_module, "_task_queue_required", lambda: False, raising=True)
    monkeypatch.setattr(documents_module, "run_document_processing_limited", _process, raising=True)
    monkeypatch.setattr(processor, "Indexer", _Indexer)

    result = await document_processing.retry_document_processing(
        document_id=document.id,
        background_tasks=background_tasks,
        force=True,
        tenant_id=document.tenant_id,
        account_id="acct-1",
        db=db,
    )

    assert result["status"] == "pending"
    assert result["current_stage"] == "queued"
    assert document.doc_metadata.get("retry_cleanup") == {
        "version": "1",
        "force": True,
        "pipeline_hash": "stable-pipeline",
        "scope": "document",
    }
    assert len(background_tasks.tasks) == 1

    await background_tasks()

    assert processing_calls == [
        {
            "file_path": source,
            "document_id": document.id,
            "tenant_id": document.tenant_id,
            "parser_backend": "auto",
            "chunk_strategy": "langchain_recursive",
            "retry_cleanup_before": {
                "version": "1",
                "force": True,
                "pipeline_hash": "stable-pipeline",
                "scope": "document",
            },
        }
    ]
    assert cleanup_calls == ["chunks", "events"]
    assert processor.DocumentParsedContent in db.deletes
    assert processor.DocumentChunk in db.deletes
    assert document.doc_metadata.get("retry_cleanup") is None
    assert document.doc_metadata.get("ingest_checkpoint") is None
    assert document.doc_metadata.get("parsed_content_persisted") is None
    assert document.doc_metadata.get("img_ids") is None
    assert document.chunk_count == 0
    assert document.total_characters == 0


def test_document_worker_applies_deferred_retry_cleanup(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.parsing.processors import processor

    document = SimpleNamespace(
        doc_metadata={
            "pipeline_hash": "stable-pipeline",
            "active_pipeline_hash": "stable-pipeline",
            "active_pipeline_ready": True,
            "img_ids": ["old-image"],
            "ingest_checkpoint": {"version": "1", "stage": "parsed"},
            "parsed_content_persisted": {"cleaned": {"text": "old parsed text"}},
            "retry_cleanup": {
                "version": "1",
                "force": True,
                "pipeline_hash": "stable-pipeline",
                "scope": "document",
            },
        },
        chunk_count=12,
        total_characters=34,
    )
    db = _DB(document)
    cleanup_calls: list[str] = []

    class _Indexer:
        def __init__(self, _db) -> None:  # noqa: ANN001
            pass

        def delete_chunk_indexes(self, **_kwargs) -> None:  # noqa: ANN003
            cleanup_calls.append("chunks")

        def delete_event_indexes(self, **_kwargs) -> None:  # noqa: ANN003
            cleanup_calls.append("events")

    monkeypatch.setattr(processor, "Indexer", _Indexer)

    assert processor.DocumentProcessorService()._apply_pending_retry_cleanup(
        db,
        db_document=document,
        tenant_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
    ) == "applied"

    assert cleanup_calls == ["chunks", "events"]
    assert processor.DocumentParsedContent in db.deletes
    assert processor.DocumentChunk in db.deletes
    assert document.doc_metadata.get("retry_cleanup") is None
    assert document.doc_metadata.get("img_ids") is None
    assert document.doc_metadata.get("ingest_checkpoint") is None
    assert document.doc_metadata.get("parsed_content_persisted") is None
    assert document.chunk_count == 0
    assert document.total_characters == 0


def test_document_worker_scoped_retry_cleanup_only_deletes_target_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.parsing.processors import processor

    document_id = uuid.uuid4()
    tenant_id = uuid.uuid4()
    pipeline_hash = "retry-pipeline"
    active_pipeline_hash = "active-pipeline"
    target_key = f"{document_id}:{pipeline_hash}"
    active_key = f"{document_id}:{active_pipeline_hash}"
    target_chunk_ids = [uuid.uuid4(), uuid.uuid4()]
    active_chunk_id = uuid.uuid4()
    document = SimpleNamespace(
        doc_metadata={
            "pipeline_hash": pipeline_hash,
            "active_pipeline_hash": active_pipeline_hash,
            "active_pipeline_ready": True,
            "ingest_checkpoint": {"version": "1", "stage": "parsed"},
            "parsed_content_persisted": {"cleaned": {"text": "staged parsed text"}},
            "retry_cleanup": {
                "version": "1",
                "force": True,
                "pipeline_hash": pipeline_hash,
                "scope": "pipeline",
                "doc_pipeline_key": target_key,
            },
        },
        chunk_count=12,
        total_characters=34,
    )
    index_calls: list[tuple[str, object]] = []

    class _ScopedQuery:
        def __init__(self, db, model) -> None:  # noqa: ANN001
            self._db = db
            self._model = model

        def filter(self, *_args, **_kwargs):  # noqa: ANN002, ANN003
            return self

        def all(self) -> list[tuple]:
            if getattr(self._model, "class_", None) is processor.DocumentChunk and getattr(self._model, "key", None) == "id":
                return [(chunk["id"],) for chunk in self._db.chunks if chunk["doc_pipeline_key"] == target_key]
            return []

        def delete(self, **_kwargs) -> int:  # noqa: ANN003
            if self._model is processor.DocumentParsedContent:
                self._db.deleted_parsed_content += 1
                return 1
            if self._model is processor.DocumentChunk:
                doomed = [chunk for chunk in self._db.chunks if chunk["doc_pipeline_key"] == target_key]
                self._db.deleted_chunk_ids.extend(chunk["id"] for chunk in doomed)
                self._db.chunks = [chunk for chunk in self._db.chunks if chunk["doc_pipeline_key"] != target_key]
                return len(doomed)
            if self._model.__name__ == "KgRelation":
                doomed = [chunk_id for chunk_id in self._db.relation_chunk_ids if chunk_id in target_chunk_ids]
                self._db.deleted_relation_chunk_ids.extend(doomed)
                self._db.relation_chunk_ids = [chunk_id for chunk_id in self._db.relation_chunk_ids if chunk_id not in target_chunk_ids]
                return len(doomed)
            return 0

    class _ScopedDB:
        def __init__(self) -> None:
            self.chunks = [
                {"id": target_chunk_ids[0], "doc_pipeline_key": target_key},
                {"id": target_chunk_ids[1], "doc_pipeline_key": target_key},
                {"id": active_chunk_id, "doc_pipeline_key": active_key},
            ]
            self.relation_chunk_ids = [target_chunk_ids[0], target_chunk_ids[1], active_chunk_id]
            self.deleted_parsed_content = 0
            self.deleted_chunk_ids: list[uuid.UUID] = []
            self.deleted_relation_chunk_ids: list[uuid.UUID] = []
            self.commits = 0
            self.rollbacks = 0

        def query(self, model):  # noqa: ANN001, ANN201
            return _ScopedQuery(self, model)

        def commit(self) -> None:
            self.commits += 1

        def refresh(self, _obj) -> None:  # noqa: ANN001
            return None

        def rollback(self) -> None:
            self.rollbacks += 1

    class _Indexer:
        def __init__(self, _db) -> None:  # noqa: ANN001
            pass

        def delete_chunk_indexes_for_doc_pipeline_key(self, **kwargs) -> None:  # noqa: ANN003
            index_calls.append(("chunk", kwargs["doc_pipeline_key"]))

        def delete_event_indexes_for_chunks(self, **kwargs) -> None:  # noqa: ANN003
            index_calls.append(("event", tuple(kwargs["chunk_ids"])))

    db = _ScopedDB()
    monkeypatch.setattr(processor, "Indexer", _Indexer)

    assert processor.DocumentProcessorService()._apply_pending_retry_cleanup(
        db,
        db_document=document,
        tenant_id=tenant_id,
        document_id=document_id,
    )

    assert db.deleted_parsed_content == 1
    assert db.deleted_chunk_ids == target_chunk_ids
    assert db.deleted_relation_chunk_ids == target_chunk_ids
    assert [chunk["doc_pipeline_key"] for chunk in db.chunks] == [active_key]
    assert db.relation_chunk_ids == [active_chunk_id]
    assert index_calls == [
        ("chunk", target_key),
        ("event", tuple(target_chunk_ids)),
    ]
    assert document.doc_metadata.get("retry_cleanup") is None
    assert document.doc_metadata.get("active_pipeline_hash") == active_pipeline_hash
    assert document.doc_metadata.get("ingest_checkpoint") is None
    assert document.doc_metadata.get("parsed_content_persisted") is None
    assert document.chunk_count == 12
    assert document.total_characters == 34


def test_document_worker_preserves_retry_cleanup_when_kg_cleanup_fails(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    from app.parsing.processors import processor

    document = SimpleNamespace(
        doc_metadata={
            "pipeline_hash": "stable-pipeline",
            "active_pipeline_hash": "stable-pipeline",
            "active_pipeline_ready": True,
            "img_ids": ["old-image"],
            "ingest_checkpoint": {"version": "1", "stage": "parsed"},
            "parsed_content_persisted": {"cleaned": {"text": "old parsed text"}},
            "retry_cleanup": {
                "version": "1",
                "force": True,
                "pipeline_hash": "stable-pipeline",
                "scope": "document",
            },
        },
        chunk_count=12,
        total_characters=34,
    )
    db = _DB(document)
    cleanup_calls: list[str] = []

    class _Indexer:
        def __init__(self, _db) -> None:  # noqa: ANN001
            pass

        def delete_chunk_indexes(self, **_kwargs) -> None:  # noqa: ANN003
            cleanup_calls.append("chunks")

        def delete_event_indexes(self, **_kwargs) -> None:  # noqa: ANN003
            cleanup_calls.append("events")
            raise RuntimeError("kg boom")

    monkeypatch.setattr(processor, "Indexer", _Indexer)

    with caplog.at_level("WARNING"):
        assert processor.DocumentProcessorService()._apply_pending_retry_cleanup(
            db,
            db_document=document,
            tenant_id=uuid.uuid4(),
            document_id=uuid.uuid4(),
        ) == "deferred"

    assert cleanup_calls == ["chunks", "events"]
    assert processor.DocumentParsedContent in db.deletes
    assert processor.DocumentChunk in db.deletes
    assert any(getattr(model, "__name__", "") == "KgRelation" for model in db.deletes)
    assert document.doc_metadata.get("retry_cleanup") == {
        "version": "1",
        "force": True,
        "pipeline_hash": "stable-pipeline",
        "scope": "document",
    }
    assert document.doc_metadata.get("img_ids") == ["old-image"]
    assert document.doc_metadata.get("ingest_checkpoint") == {"version": "1", "stage": "parsed"}
    assert document.doc_metadata.get("parsed_content_persisted") == {"cleaned": {"text": "old parsed text"}}
    assert document.chunk_count == 12
    assert document.total_characters == 34
    assert db.commits == 0
    assert db.rollbacks == 1
    assert "keeping retry cleanup marker for a later retry" in caplog.text


@pytest.mark.asyncio
async def test_document_processing_stops_when_retry_cleanup_is_deferred(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app.parsing.processors import processor

    document_id = uuid.uuid4()
    tenant_id = uuid.uuid4()
    document = SimpleNamespace(id=document_id, tenant_id=tenant_id, dataset_id=None, doc_metadata={})
    db = _DB(document)
    service = processor.DocumentProcessorService()
    status_updates: list[tuple[str, str, str | None]] = []

    async def _cancel_check(*, force: bool = False) -> bool:
        return False

    async def _update_status(
        _db,
        _tenant_id,
        _document_id,
        status,
        _progress,
        stage,
        *,
        error_message=None,
        **_kwargs,
    ):  # noqa: ANN001, ANN003, ANN202
        if status == "processing":
            raise AssertionError("processing must not continue after deferred retry cleanup")
        status_updates.append((status, stage, error_message))

    monkeypatch.setattr(service, "_build_cancel_check", lambda **_kwargs: _cancel_check, raising=True)
    monkeypatch.setattr(service, "_apply_pending_retry_cleanup", lambda *_args, **_kwargs: "deferred", raising=True)
    monkeypatch.setattr(service, "_update_status", _update_status, raising=True)

    result = await service.process_document(
        file_path=tmp_path / "unused.txt",
        document_id=document_id,
        tenant_id=tenant_id,
        db=db,
    )

    assert result == {"status": "failed", "reason": "retry_cleanup_deferred"}
    assert status_updates == [("failed", "failed", "retry_cleanup_deferred")]

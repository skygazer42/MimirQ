from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi import BackgroundTasks, HTTPException

from app.api.schemas.document import DocumentPipelineOptions, DocumentPipelinePatchRequest
from tests.helpers.async_utils import yield_control


class _FakeQuery:
    def __init__(self, *, first=None, delete_count: int = 0):  # noqa: ANN001
        self._first = first
        self._delete_count = int(delete_count or 0)
        self.delete_called = False

    def filter(self, *_args, **_kwargs):  # noqa: ANN001
        return self

    def first(self):  # noqa: ANN001
        return self._first

    def delete(self, *_args, **_kwargs):  # noqa: ANN001
        self.delete_called = True
        return self._delete_count


class _FakeDB:
    def __init__(self, queries):  # noqa: ANN001
        self._queries = list(queries)
        self.commits = 0
        self.rollbacks = 0

    def query(self, *_args, **_kwargs):  # noqa: ANN001
        if not self._queries:
            raise AssertionError("Unexpected db.query call")
        return self._queries.pop(0)

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1

    def refresh(self, _obj) -> None:  # noqa: ANN001
        return


def _uploaded_only_doc(*, document_id: UUID, tenant_id: UUID, file_path: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=document_id,
        tenant_id=tenant_id,
        dataset_id=None,
        status="pending",
        file_path=file_path,
        file_type="txt",
        filename="doc.txt",
        doc_metadata={
            "ingest_stage": "uploaded_only",
            "active_pipeline_ready": False,
        },
        processing_progress=0,
        current_stage=None,
        failed_stage=None,
        error_code=None,
        processing_attempts=0,
        next_retry_at=None,
        error_message=None,
        chunk_count=0,
        total_characters=0,
    )


@pytest.mark.asyncio
async def test_patch_pipeline_allows_uploaded_only_pending_document(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    import app.api.v1.documents as docs_mod
    from app.api.v1.documents import patch_document_pipeline
    from app.services.dataset_service import DatasetService

    monkeypatch.setattr(DatasetService, "ensure_member", lambda *_args, **_kwargs: None, raising=True)
    monkeypatch.setattr(docs_mod, "audit_log_event", lambda *_args, **_kwargs: None, raising=True)
    monkeypatch.setattr(docs_mod, "_compute_pipeline_hash", lambda _meta: "hash123", raising=True)

    tenant_id = UUID(int=1)
    document_id = UUID(int=2)
    path = tmp_path / "doc.txt"
    path.write_text("hello", encoding="utf-8")
    document = _uploaded_only_doc(document_id=document_id, tenant_id=tenant_id, file_path=str(path))
    db = _FakeDB([_FakeQuery(first=document)])

    await patch_document_pipeline(
        document_id=document_id,
        payload=DocumentPipelinePatchRequest(
            patch=DocumentPipelineOptions(
                governance_enabled=True,
                governance_python_plugin="plugin:demo@1.0.0:governance",
                chunk_python_plugin="plugin:demo@1.0.0:chunk",
                chunk_vector_enabled=True,
                bm25_index_enabled=True,
            ),
            replace=False,
        ),
        tenant_id=tenant_id,
        account_id="u",
        db=db,
    )

    assert document.doc_metadata["pipeline_hash"] == "hash123"
    assert document.doc_metadata["pipeline"]["governance_enabled"] is True
    assert document.doc_metadata["pipeline"]["governance"]["python_plugin"] == "plugin:demo@1.0.0:governance"
    assert document.doc_metadata["pipeline"]["chunk_python_plugin"] == "plugin:demo@1.0.0:chunk"
    assert document.doc_metadata["pipeline"]["index"]["chunk_vector_enabled"] is True
    assert document.doc_metadata["pipeline"]["index"]["bm25_index_enabled"] is True


@pytest.mark.asyncio
async def test_patch_pipeline_allows_idle_pending_document(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    import app.api.v1.documents as docs_mod
    from app.api.v1.documents import patch_document_pipeline
    from app.services.dataset_service import DatasetService

    monkeypatch.setattr(DatasetService, "ensure_member", lambda *_args, **_kwargs: None, raising=True)
    monkeypatch.setattr(docs_mod, "audit_log_event", lambda *_args, **_kwargs: None, raising=True)
    monkeypatch.setattr(docs_mod, "_compute_pipeline_hash", lambda _meta: "hash-idle", raising=True)

    tenant_id = UUID(int=1)
    document_id = UUID(int=2)
    path = tmp_path / "doc.txt"
    path.write_text("hello", encoding="utf-8")
    document = _uploaded_only_doc(document_id=document_id, tenant_id=tenant_id, file_path=str(path))
    document.doc_metadata = {}
    db = _FakeDB([_FakeQuery(first=document)])

    await patch_document_pipeline(
        document_id=document_id,
        payload=DocumentPipelinePatchRequest(
            patch=DocumentPipelineOptions(governance_enabled=True),
            replace=False,
        ),
        tenant_id=tenant_id,
        account_id="u",
        db=db,
    )

    assert document.doc_metadata["pipeline_hash"] == "hash-idle"
    assert document.doc_metadata["pipeline"]["governance_enabled"] is True


@pytest.mark.asyncio
async def test_retry_processing_allows_uploaded_only_pending_document(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    import app.api.v1.documents as docs_mod
    from app.api.v1.documents import retry_document_processing
    from app.services.dataset_service import DatasetService

    monkeypatch.setattr(DatasetService, "ensure_member", lambda *_args, **_kwargs: None, raising=True)
    monkeypatch.setattr(docs_mod, "audit_log_event", lambda *_args, **_kwargs: None, raising=True)
    monkeypatch.setattr(docs_mod, "_compute_pipeline_hash", lambda _meta: "hash123", raising=True)

    async def _noop_enqueue(*_args, **_kwargs):  # noqa: ANN001
        await yield_control()
        return None

    monkeypatch.setattr(docs_mod, "enqueue_document_processing", _noop_enqueue, raising=True)

    class _FakeIndexer:
        def __init__(self, _db):  # noqa: ANN001
            return

        def delete_chunk_indexes(self, **_kwargs):  # noqa: ANN003
            return

        def delete_event_indexes(self, **_kwargs):  # noqa: ANN003
            return {"events_deleted": 0}

    monkeypatch.setattr(docs_mod, "Indexer", _FakeIndexer, raising=True)

    tenant_id = UUID(int=1)
    document_id = UUID(int=2)
    path = tmp_path / "doc.txt"
    path.write_text("hello", encoding="utf-8")
    document = _uploaded_only_doc(document_id=document_id, tenant_id=tenant_id, file_path=str(path))
    db = _FakeDB([
        _FakeQuery(first=document),
        _FakeQuery(delete_count=0),
        _FakeQuery(delete_count=0),
    ])

    status = await retry_document_processing(
        document_id=document_id,
        background_tasks=BackgroundTasks(),
        force=True,
        skip_if_unchanged=False,
        tenant_id=tenant_id,
        account_id="u",
        db=db,
    )

    assert status["status"] == "pending"
    assert document.current_stage == "queued"
    assert document.doc_metadata["pipeline_hash"] == "hash123"


@pytest.mark.asyncio
async def test_retry_processing_allows_idle_pending_document(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    import app.api.v1.documents as docs_mod
    from app.api.v1.documents import retry_document_processing
    from app.services.dataset_service import DatasetService

    monkeypatch.setattr(DatasetService, "ensure_member", lambda *_args, **_kwargs: None, raising=True)
    monkeypatch.setattr(docs_mod, "audit_log_event", lambda *_args, **_kwargs: None, raising=True)
    monkeypatch.setattr(docs_mod, "_compute_pipeline_hash", lambda _meta: "hash-idle", raising=True)

    async def _noop_enqueue(*_args, **_kwargs):  # noqa: ANN001
        await yield_control()
        return None

    monkeypatch.setattr(docs_mod, "enqueue_document_processing", _noop_enqueue, raising=True)

    class _FakeIndexer:
        def __init__(self, _db):  # noqa: ANN001
            return

        def delete_chunk_indexes(self, **_kwargs):  # noqa: ANN003
            return

        def delete_event_indexes(self, **_kwargs):  # noqa: ANN003
            return {"events_deleted": 0}

    monkeypatch.setattr(docs_mod, "Indexer", _FakeIndexer, raising=True)

    tenant_id = UUID(int=1)
    document_id = UUID(int=2)
    path = tmp_path / "doc.txt"
    path.write_text("hello", encoding="utf-8")
    document = _uploaded_only_doc(document_id=document_id, tenant_id=tenant_id, file_path=str(path))
    document.doc_metadata = {}
    db = _FakeDB([
        _FakeQuery(first=document),
        _FakeQuery(delete_count=0),
        _FakeQuery(delete_count=0),
    ])

    status = await retry_document_processing(
        document_id=document_id,
        background_tasks=BackgroundTasks(),
        force=True,
        skip_if_unchanged=False,
        tenant_id=tenant_id,
        account_id="u",
        db=db,
    )

    assert status["status"] == "pending"
    assert document.current_stage == "queued"
    assert document.doc_metadata["pipeline_hash"] == "hash-idle"


@pytest.mark.asyncio
async def test_retry_processing_applies_requested_parser_backend(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    import app.api.v1.document_processing as processing_mod

    captured_meta: dict[str, object] = {}

    def _compute_hash(meta: dict) -> str:
        captured_meta.update(meta)
        return "hash-parser"

    async def _noop_enqueue(*_args, **_kwargs):  # noqa: ANN001
        await yield_control()
        return None

    class _FakeIndexer:
        def __init__(self, _db):  # noqa: ANN001
            return

        def delete_chunk_indexes(self, **_kwargs):  # noqa: ANN003
            return

        def delete_event_indexes(self, **_kwargs):  # noqa: ANN003
            return {"events_deleted": 0}

    fake_documents = SimpleNamespace(
        DatasetService=SimpleNamespace(
            ensure_member=lambda *_args, **_kwargs: None,
            get_dataset=lambda *_args, **_kwargs: None,
            assert_dataset_writable=lambda *_args, **_kwargs: None,
        ),
        DOC_NOT_FOUND_DETAIL="Document not found",
        DOCUMENT_FILE_NOT_FOUND_DETAIL="Document file not found",
        DOCUMENT_FILE_ACCESS_DENIED_DETAIL="Document file access denied",
        MANUAL_FILE_PATH_PREFIX="manual://",
        settings=SimpleNamespace(MINIO_ENABLED=False, UPLOAD_DIR=str(tmp_path), MINIO_BUCKET_NAME=""),
        audit_log_event=lambda *_args, **_kwargs: None,
        _compute_pipeline_hash=_compute_hash,
        _is_uploaded_only_pending_document=lambda document: bool(
            (getattr(document, "doc_metadata", None) or {}).get("ingest_stage") == "uploaded_only"
        ),
        _is_reprocessable_pending_document=lambda document: bool(
            (getattr(document, "doc_metadata", None) or {}).get("ingest_stage") == "uploaded_only"
        ),
        parser_factory=SimpleNamespace(resolve_backend=lambda _ext, backend: backend),
        is_minio_uri=lambda _path: False,
        enqueue_document_processing=_noop_enqueue,
        Indexer=_FakeIndexer,
        run_document_processing_limited=lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(processing_mod, "_documents_module", lambda: fake_documents, raising=True)

    tenant_id = UUID(int=1)
    document_id = UUID(int=2)
    path = tmp_path / "doc.html"
    path.write_text("<p>hello</p>", encoding="utf-8")
    document = _uploaded_only_doc(document_id=document_id, tenant_id=tenant_id, file_path=str(path))
    document.file_type = "html"
    document.filename = "doc.html"
    document.doc_metadata["parser_backend"] = "auto"
    document.doc_metadata["parser_backend_requested"] = "auto"
    db = _FakeDB([
        _FakeQuery(first=document),
        _FakeQuery(delete_count=0),
        _FakeQuery(delete_count=0),
    ])

    status = await processing_mod.retry_document_processing(
        document_id=document_id,
        background_tasks=BackgroundTasks(),
        force=True,
        skip_if_unchanged=False,
        parser_backend="pandoc",
        tenant_id=tenant_id,
        account_id="u",
        db=db,
    )

    assert status["status"] == "pending"
    assert document.doc_metadata["parser_backend_requested"] == "pandoc"
    assert document.doc_metadata["parser_backend"] == "pandoc"
    assert document.doc_metadata["pipeline_hash"] == "hash-parser"
    assert captured_meta["parser_backend_requested"] == "pandoc"
    assert captured_meta["parser_backend"] == "pandoc"


@pytest.mark.asyncio
async def test_force_retry_clears_parsed_checkpoint(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    import app.api.v1.document_processing as processing_mod
    from app.models.document import Document as DBDocument
    from app.models.document import DocumentParsedContent

    async def _noop_enqueue(*_args, **_kwargs):  # noqa: ANN001
        await yield_control()
        return None

    class _FakeIndexer:
        def __init__(self, _db):  # noqa: ANN001
            return

        def delete_chunk_indexes(self, **_kwargs):  # noqa: ANN003
            return

        def delete_event_indexes(self, **_kwargs):  # noqa: ANN003
            return {"events_deleted": 0}

    fake_documents = SimpleNamespace(
        DatasetService=SimpleNamespace(
            ensure_member=lambda *_args, **_kwargs: None,
            get_dataset=lambda *_args, **_kwargs: None,
            assert_dataset_writable=lambda *_args, **_kwargs: None,
        ),
        DOC_NOT_FOUND_DETAIL="Document not found",
        DOCUMENT_FILE_NOT_FOUND_DETAIL="Document file not found",
        DOCUMENT_FILE_ACCESS_DENIED_DETAIL="Document file access denied",
        MANUAL_FILE_PATH_PREFIX="manual://",
        settings=SimpleNamespace(MINIO_ENABLED=False, UPLOAD_DIR=str(tmp_path), MINIO_BUCKET_NAME=""),
        audit_log_event=lambda *_args, **_kwargs: None,
        _compute_pipeline_hash=lambda _meta: "hash-reparse",
        _is_uploaded_only_pending_document=lambda _document: False,
        _is_reprocessable_pending_document=lambda _document: False,
        parser_factory=SimpleNamespace(resolve_backend=lambda _ext, backend: backend),
        is_minio_uri=lambda _path: False,
        enqueue_document_processing=_noop_enqueue,
        Indexer=_FakeIndexer,
        run_document_processing_limited=lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(processing_mod, "_documents_module", lambda: fake_documents, raising=True)

    tenant_id = UUID(int=1)
    document_id = UUID(int=2)
    path = tmp_path / "doc.pdf"
    path.write_bytes(b"%PDF-1.4\n")
    document = SimpleNamespace(
        id=document_id,
        tenant_id=tenant_id,
        dataset_id=None,
        status="completed",
        file_path=str(path),
        file_type="pdf",
        filename="doc.pdf",
        doc_metadata={
            "ingest_checkpoint": {"version": "1", "stage": "parsed"},
            "parsed_content_persisted": {"enabled": True},
            "active_pipeline_ready": True,
            "active_pipeline_hash": "hash-reparse",
            "pipeline_hash": "hash-reparse",
        },
        processing_progress=100,
        current_stage="completed",
        failed_stage=None,
        error_code=None,
        processing_attempts=0,
        next_retry_at=None,
        error_message=None,
        chunk_count=1,
        total_characters=10,
    )

    class _ModelQuery:
        def __init__(self, first=None):  # noqa: ANN001
            self._first = first
            self.delete_called = False

        def filter(self, *_args, **_kwargs):  # noqa: ANN001
            return self

        def first(self):  # noqa: ANN201
            return self._first

        def delete(self, *_args, **_kwargs):  # noqa: ANN001
            self.delete_called = True
            return 1

    parsed_query = _ModelQuery()
    chunk_query = _ModelQuery()
    other_delete_query = _ModelQuery()

    class _ModelDB:
        def query(self, model):  # noqa: ANN001, ANN201
            if model is DBDocument:
                return _ModelQuery(first=document)
            if model is DocumentParsedContent:
                return parsed_query
            if model is processing_mod.DocumentChunk:
                return chunk_query
            return other_delete_query

        def commit(self) -> None:
            return None

        def rollback(self) -> None:
            return None

        def refresh(self, _obj) -> None:  # noqa: ANN001
            return None

    status = await processing_mod.retry_document_processing(
        document_id=document_id,
        background_tasks=BackgroundTasks(),
        force=True,
        skip_if_unchanged=False,
        parser_backend="mineru",
        tenant_id=tenant_id,
        account_id="u",
        db=_ModelDB(),
    )

    assert status["status"] == "pending"
    assert "ingest_checkpoint" not in document.doc_metadata
    assert "parsed_content_persisted" not in document.doc_metadata
    assert parsed_query.delete_called is True


@pytest.mark.asyncio
async def test_retry_processing_still_rejects_ordinary_pending_document(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    from app.api.v1.documents import retry_document_processing
    from app.services.dataset_service import DatasetService

    monkeypatch.setattr(DatasetService, "ensure_member", lambda *_args, **_kwargs: None, raising=True)

    tenant_id = UUID(int=1)
    document_id = UUID(int=2)
    path = tmp_path / "doc.txt"
    path.write_text("hello", encoding="utf-8")
    document = _uploaded_only_doc(document_id=document_id, tenant_id=tenant_id, file_path=str(path))
    document.doc_metadata = {}
    document.current_stage = "queued"
    db = _FakeDB([_FakeQuery(first=document)])

    with pytest.raises(HTTPException) as excinfo:
        await retry_document_processing(
            document_id=document_id,
            background_tasks=BackgroundTasks(),
            force=True,
            skip_if_unchanged=False,
            tenant_id=tenant_id,
            account_id="u",
            db=db,
        )

    assert excinfo.value.status_code == 409
    assert "pending" in str(excinfo.value.detail)

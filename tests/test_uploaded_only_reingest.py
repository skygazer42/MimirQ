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
async def test_retry_processing_still_rejects_ordinary_pending_document(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    import app.api.v1.documents as docs_mod
    from app.api.v1.documents import retry_document_processing
    from app.services.dataset_service import DatasetService

    monkeypatch.setattr(DatasetService, "ensure_member", lambda *_args, **_kwargs: None, raising=True)

    tenant_id = UUID(int=1)
    document_id = UUID(int=2)
    path = tmp_path / "doc.txt"
    path.write_text("hello", encoding="utf-8")
    document = _uploaded_only_doc(document_id=document_id, tenant_id=tenant_id, file_path=str(path))
    document.doc_metadata = {}
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

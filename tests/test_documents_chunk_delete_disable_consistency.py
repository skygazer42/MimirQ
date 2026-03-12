from __future__ import annotations

import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.core.database import get_db


class _FakeQuery:
    def __init__(self, row) -> None:  # noqa: ANN001
        self._row = row

    def filter(self, *_args, **_kwargs):  # noqa: ANN001, ANN202
        return self

    def first(self):  # noqa: D401
        return self._row


class _FakeDB:
    def __init__(self, *, docs_module, document, chunk) -> None:  # noqa: ANN001
        self._docs_module = docs_module
        self._document = document
        self._chunk = chunk
        self.added: list[object] = []
        self.deleted: list[object] = []

    def query(self, model):  # noqa: ANN001
        if model is self._docs_module.DBDocument:
            return _FakeQuery(self._document)
        if model is self._docs_module.DocumentChunk:
            return _FakeQuery(self._chunk)
        return _FakeQuery(None)

    def add(self, obj) -> None:  # noqa: ANN001
        self.added.append(obj)

    def delete(self, obj) -> None:  # noqa: ANN001
        self.deleted.append(obj)

    def commit(self) -> None:
        return None

    def refresh(self, _obj) -> None:  # noqa: ANN001
        return None

    def rollback(self) -> None:
        return None


def test_delete_chunk_strict_mode_records_drift_item_and_returns_409(monkeypatch):  # noqa: ANN001
    import app.api.v1.documents as documents_module
    from app.models.index_drift_item import IndexDriftItem

    tenant_id = uuid.uuid4()
    document_id = uuid.uuid4()
    chunk_id = uuid.uuid4()
    active_key = f"{document_id}:h"

    class _Doc:
        def __init__(self) -> None:
            self.id = document_id
            self.tenant_id = tenant_id
            self.dataset_id = None
            self.status = "completed"
            self.filename = "demo.txt"
            self.doc_metadata = {"pipeline_hash": "h"}

    class _Chunk:
        def __init__(self) -> None:
            self.id = chunk_id
            self.tenant_id = tenant_id
            self.document_id = document_id
            self.chunk_index = 0
            self.content = "hello"
            self.page_number = None
            self.start_char = None
            self.end_char = None
            self.vector_id = "vec_old"
            self.doc_metadata = {"doc_pipeline_key": active_key, "chunk_id": str(chunk_id), "pipeline_hash": "h"}
            self.disabled_at = None

    document = _Doc()
    chunk = _Chunk()
    db = _FakeDB(docs_module=documents_module, document=document, chunk=chunk)

    def _override_get_db():  # noqa: ANN202
        yield db

    def _override_get_tenant_id() -> uuid.UUID:
        return tenant_id

    def _override_get_current_account_id() -> str:
        return "u"

    class _VectorStore:
        def delete_by_document_id_and_filter(self, **_kwargs):  # noqa: ANN001
            raise RuntimeError("vector delete failed")

    class _HybridRetriever:
        def remove_from_bm25_index_by_metadata_filter(self, **_kwargs):  # noqa: ANN001
            return None

    async def _fake_enqueue_rebuild_indexes(**_kwargs):  # noqa: ANN001, ANN202
        return "task-1"

    monkeypatch.setattr("app.storage.vector.factory.get_vector_store", lambda: _VectorStore(), raising=True)
    monkeypatch.setattr("app.rag.retriever.hybrid_retriever", _HybridRetriever(), raising=True)
    monkeypatch.setattr("app.tasks.queue.enqueue_rebuild_indexes", _fake_enqueue_rebuild_indexes, raising=True)
    monkeypatch.setattr(documents_module.DatasetService, "ensure_member", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(documents_module, "_assert_document_acl_readable", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(documents_module, "audit_log_event", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(documents_module.settings, "INDEX_CONSISTENCY_ENABLED", True, raising=False)
    monkeypatch.setattr(documents_module.settings, "INDEX_CONSISTENCY_STRICTNESS", "strict", raising=False)
    monkeypatch.setattr(documents_module.settings, "INDEX_CONSISTENCY_EMIT_DRIFT_MARKERS", True, raising=False)
    monkeypatch.setattr(documents_module.settings, "TASK_QUEUE_ENABLED", True, raising=False)

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = _override_get_tenant_id
    app.dependency_overrides[get_current_account_id] = _override_get_current_account_id
    app.delete("/api/v1/documents/{document_id}/chunks/{chunk_id}")(documents_module.delete_document_chunk)
    client = TestClient(app)

    res = client.delete(f"/api/v1/documents/{document_id}/chunks/{chunk_id}")
    assert res.status_code == 409, res.text

    assert db.deleted == []

    op = (chunk.doc_metadata or {}).get("index_operation_result") or {}
    assert op.get("schema") == "mimirq.index_operation_result.v1"
    assert op.get("operation") == "chunk.delete"
    assert op.get("strictness") == "strict"
    assert op.get("success") is False

    markers = (chunk.doc_metadata or {}).get("index_drift_markers") or []
    assert isinstance(markers, list) and markers
    assert markers[-1]["operation"] == "chunk.delete"

    drift_items = [item for item in db.added if isinstance(item, IndexDriftItem)]
    assert len(drift_items) == 1
    assert drift_items[0].operation == "chunk.delete"
    assert drift_items[0].channel == "vector"
    assert drift_items[0].status == "open"
    assert drift_items[0].reconcile_task_id == "task-1"


def test_disable_chunk_strict_mode_records_drift_item_and_returns_409(monkeypatch):  # noqa: ANN001
    import app.api.v1.documents as documents_module
    from app.models.index_drift_item import IndexDriftItem

    tenant_id = uuid.uuid4()
    document_id = uuid.uuid4()
    chunk_id = uuid.uuid4()
    active_key = f"{document_id}:h"

    class _Doc:
        def __init__(self) -> None:
            self.id = document_id
            self.tenant_id = tenant_id
            self.dataset_id = None
            self.status = "completed"
            self.filename = "demo.txt"
            self.doc_metadata = {"pipeline_hash": "h"}

    class _Chunk:
        def __init__(self) -> None:
            self.id = chunk_id
            self.tenant_id = tenant_id
            self.document_id = document_id
            self.chunk_index = 0
            self.content = "hello"
            self.page_number = None
            self.start_char = None
            self.end_char = None
            self.vector_id = "vec_old"
            self.doc_metadata = {"doc_pipeline_key": active_key, "chunk_id": str(chunk_id), "pipeline_hash": "h"}
            self.disabled_at = None

    document = _Doc()
    chunk = _Chunk()
    db = _FakeDB(docs_module=documents_module, document=document, chunk=chunk)

    def _override_get_db():  # noqa: ANN202
        yield db

    def _override_get_tenant_id() -> uuid.UUID:
        return tenant_id

    def _override_get_current_account_id() -> str:
        return "u"

    class _VectorStore:
        def delete_by_document_id_and_filter(self, **_kwargs):  # noqa: ANN001
            raise RuntimeError("vector delete failed")

    class _HybridRetriever:
        def remove_from_bm25_index_by_metadata_filter(self, **_kwargs):  # noqa: ANN001
            return None

    async def _fake_enqueue_rebuild_indexes(**_kwargs):  # noqa: ANN001, ANN202
        return "task-2"

    monkeypatch.setattr("app.storage.vector.factory.get_vector_store", lambda: _VectorStore(), raising=True)
    monkeypatch.setattr("app.rag.retriever.hybrid_retriever", _HybridRetriever(), raising=True)
    monkeypatch.setattr("app.tasks.queue.enqueue_rebuild_indexes", _fake_enqueue_rebuild_indexes, raising=True)
    monkeypatch.setattr(documents_module.DatasetService, "ensure_member", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(documents_module, "_get_document_for_chunk_ops", lambda *_a, **_k: document, raising=True)
    monkeypatch.setattr(documents_module, "_get_chunk_for_chunk_ops", lambda *_a, **_k: chunk, raising=True)
    monkeypatch.setattr(documents_module, "_assert_document_writable_for_chunk_ops", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(documents_module, "audit_log_event", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(documents_module.settings, "INDEX_CONSISTENCY_ENABLED", True, raising=False)
    monkeypatch.setattr(documents_module.settings, "INDEX_CONSISTENCY_STRICTNESS", "strict", raising=False)
    monkeypatch.setattr(documents_module.settings, "INDEX_CONSISTENCY_EMIT_DRIFT_MARKERS", True, raising=False)
    monkeypatch.setattr(documents_module.settings, "TASK_QUEUE_ENABLED", True, raising=False)

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = _override_get_tenant_id
    app.dependency_overrides[get_current_account_id] = _override_get_current_account_id
    app.post("/api/v1/documents/{document_id}/chunks/{chunk_id}/disable")(documents_module.disable_document_chunk)
    client = TestClient(app)

    res = client.post(f"/api/v1/documents/{document_id}/chunks/{chunk_id}/disable")
    assert res.status_code == 409, res.text

    assert chunk.disabled_at is None
    assert chunk.vector_id == "vec_old"

    op = (chunk.doc_metadata or {}).get("index_operation_result") or {}
    assert op.get("schema") == "mimirq.index_operation_result.v1"
    assert op.get("operation") == "chunk.disable"
    assert op.get("strictness") == "strict"
    assert op.get("success") is False

    markers = (chunk.doc_metadata or {}).get("index_drift_markers") or []
    assert isinstance(markers, list) and markers
    assert markers[-1]["operation"] == "chunk.disable"

    drift_items = [item for item in db.added if isinstance(item, IndexDriftItem)]
    assert len(drift_items) == 1
    assert drift_items[0].operation == "chunk.disable"
    assert drift_items[0].channel == "vector"
    assert drift_items[0].status == "open"
    assert drift_items[0].reconcile_task_id == "task-2"

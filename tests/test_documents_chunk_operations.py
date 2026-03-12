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

    def query(self, model):  # noqa: ANN001
        if model is self._docs_module.DBDocument:
            return _FakeQuery(self._document)
        if model is self._docs_module.DocumentChunk:
            return _FakeQuery(self._chunk)
        return _FakeQuery(None)

    def commit(self) -> None:
        return None

    def refresh(self, _obj) -> None:  # noqa: ANN001
        return None

    def rollback(self) -> None:
        return None


def test_patch_chunk_response_includes_index_operation_contract(monkeypatch):  # noqa: ANN001
    import app.api.v1.documents as documents_module

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
            return None

        def add_documents(self, _docs, *_args, **_kwargs):  # noqa: ANN001
            return ["vec_new"]

    monkeypatch.setattr("app.storage.vector.factory.get_vector_store", lambda: _VectorStore(), raising=True)
    monkeypatch.setattr(documents_module.DatasetService, "ensure_member", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(documents_module, "_assert_document_acl_readable", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(documents_module.Indexer, "_update_bm25_for_chunks", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(documents_module.settings, "INDEX_CONSISTENCY_ENABLED", True, raising=False)
    monkeypatch.setattr(documents_module.settings, "INDEX_CONSISTENCY_STRICTNESS", "warn", raising=False)
    monkeypatch.setattr(documents_module.settings, "INDEX_CONSISTENCY_PATCH_CHUNK_STRICT", False, raising=False)
    monkeypatch.setattr(documents_module.settings, "INDEX_CONSISTENCY_EMIT_DRIFT_MARKERS", True, raising=False)

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = _override_get_tenant_id
    app.dependency_overrides[get_current_account_id] = _override_get_current_account_id
    app.patch("/api/v1/documents/{document_id}/chunks/{chunk_id}")(documents_module.patch_document_chunk)
    client = TestClient(app)

    res = client.patch(f"/api/v1/documents/{document_id}/chunks/{chunk_id}", json={"content": "hello-v2"})
    assert res.status_code == 200, res.text

    contract = (chunk.doc_metadata or {}).get("index_operation_result")
    assert isinstance(contract, dict)
    assert contract["schema"] == "mimirq.index_operation_result.v1"
    assert contract["success"] is True
    assert contract["vector"]["status"] == "ok"
    assert contract["bm25"]["status"] == "ok"

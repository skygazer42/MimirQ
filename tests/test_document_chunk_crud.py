from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.core.database import get_db


class _DummyDB:
    def commit(self) -> None:
        return None

    def refresh(self, _obj) -> None:  # noqa: ANN001
        return None

    def rollback(self) -> None:
        return None


def _override_get_db():  # noqa: ANN202
    yield _DummyDB()


def test_document_chunk_disable_enable_and_reembed(monkeypatch):  # noqa: ANN001
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
            self.doc_metadata = {"active_pipeline_ready": True, "pipeline_hash": "h"}

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
            self.disabled_at = None
            self.vector_id = "vec_old"
            self.doc_metadata = {"doc_pipeline_key": active_key, "chunk_id": str(chunk_id), "pipeline_hash": "h"}

    doc = _Doc()
    chunk = _Chunk()

    def _override_get_tenant_id() -> uuid.UUID:
        return tenant_id

    def _override_get_current_account_id() -> str:
        return "test-account"

    monkeypatch.setattr(documents_module.DatasetService, "ensure_member", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(documents_module, "_assert_document_writable_for_chunk_ops", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(documents_module, "_get_document_for_chunk_ops", lambda *_a, **_k: doc, raising=True)
    monkeypatch.setattr(documents_module, "_get_chunk_for_chunk_ops", lambda *_a, **_k: chunk, raising=True)

    class _VectorStore:
        def __init__(self) -> None:
            self.deleted = 0
            self.added = 0

        def delete_by_document_id_and_filter(self, **_kwargs):  # noqa: ANN001
            self.deleted += 1

        def add_documents(self, _docs, *_a, **_k):  # noqa: ANN001
            self.added += 1
            return ["vec_new"]

    vector_store = _VectorStore()

    monkeypatch.setattr("app.storage.vector.factory.get_vector_store", lambda: vector_store, raising=True)
    monkeypatch.setattr(documents_module.Indexer, "_update_bm25_for_chunks", lambda *_a, **_k: None, raising=True)

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = _override_get_tenant_id
    app.dependency_overrides[get_current_account_id] = _override_get_current_account_id

    app.post("/api/v1/documents/{document_id}/chunks/{chunk_id}/disable")(documents_module.disable_document_chunk)
    app.post("/api/v1/documents/{document_id}/chunks/{chunk_id}/enable")(documents_module.enable_document_chunk)
    app.post("/api/v1/documents/{document_id}/chunks/reembed")(documents_module.reembed_document_chunks)

    client = TestClient(app)

    res = client.post(f"/api/v1/documents/{document_id}/chunks/{chunk_id}/disable")
    assert res.status_code == 200, res.text
    assert isinstance(chunk.disabled_at, datetime)

    res = client.post(f"/api/v1/documents/{document_id}/chunks/{chunk_id}/enable")
    assert res.status_code == 200, res.text
    assert chunk.disabled_at is None

    res = client.post(
        f"/api/v1/documents/{document_id}/chunks/reembed",
        json={"chunk_ids": [str(chunk_id)]},
    )
    assert res.status_code == 200, res.text
    assert res.json()["reembedded"] == 1
    assert chunk.vector_id == "vec_new"
    assert vector_store.added >= 1


from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.core.database import get_db


class _DummyDB:
    def add(self, _obj) -> None:  # noqa: ANN001
        return None

    def flush(self) -> None:
        return None

    def commit(self) -> None:
        return None

    def rollback(self) -> None:
        return None

    def refresh(self, obj) -> None:  # noqa: ANN001
        now = datetime.now(UTC)
        if getattr(obj, "chunk_count", None) is None:
            obj.chunk_count = 0
        if getattr(obj, "total_characters", None) is None:
            obj.total_characters = 0
        if getattr(obj, "processing_attempts", None) is None:
            obj.processing_attempts = 0
        if getattr(obj, "created_at", None) is None:
            obj.created_at = now
        if getattr(obj, "updated_at", None) is None:
            obj.updated_at = now
        return None


def _override_get_db():  # noqa: ANN202
    yield _DummyDB()


@pytest.mark.parametrize("minio_enabled", [False, True])
def test_manual_document_endpoint_still_creates_documents_after_router_split(monkeypatch, minio_enabled: bool) -> None:
    import app.api.v1.document_manual as manual_module
    import app.api.v1.documents as documents_module
    from app.api.schemas.document import DocumentDetail
    from app.api.v1.documents import create_document_with_manual_chunks
    from app.core.config import settings

    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()

    class _Dataset:
        def __init__(self, dataset_id0: uuid.UUID) -> None:
            self.id = dataset_id0
            self.dataset_metadata = {}

    monkeypatch.setattr(settings, "MINIO_ENABLED", minio_enabled, raising=False)
    monkeypatch.setattr(
        documents_module,
        "_resolve_writable_dataset",
        lambda *_args, **_kwargs: _Dataset(dataset_id),
        raising=True,
    )
    monkeypatch.setattr(documents_module, "_to_pipeline_options", lambda **_kwargs: None, raising=True)
    monkeypatch.setattr(
        documents_module,
        "resolve_pipeline_effective",
        lambda **_kwargs: SimpleNamespace(kg_enabled=False),
        raising=True,
    )
    monkeypatch.setattr(documents_module, "build_indexing_options", lambda *_args, **_kwargs: {"bm25": True}, raising=True)
    monkeypatch.setattr(documents_module, "upsert_pipeline_metadata", lambda *_args, **_kwargs: None, raising=True)
    monkeypatch.setattr(documents_module, "_compute_pipeline_hash", lambda *_args, **_kwargs: "pipeline-hash-1", raising=True)

    class _FakeIndexer:
        def __init__(self, _db) -> None:  # noqa: ANN001
            return None

        def upsert(self, *, tenant_id, records, default_source, options, commit):  # noqa: ANN001
            assert tenant_id == test_tenant_id
            assert default_source == "Manual Doc"
            assert options == {"bm25": True}
            assert commit is False
            assert len(records) == 2
            return SimpleNamespace(
                chunk_result=SimpleNamespace(
                    chunk_ids=[uuid.uuid4(), uuid.uuid4()],
                    db_chunks=[SimpleNamespace(id=uuid.uuid4()), SimpleNamespace(id=uuid.uuid4())],
                    total_characters=sum(len(record.content or "") for record in records),
                )
            )

        def delete_chunk_indexes(self, **_kwargs) -> None:
            return None

    monkeypatch.setattr(manual_module, "Indexer", _FakeIndexer, raising=True)

    test_tenant_id = tenant_id

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = lambda: tenant_id
    app.dependency_overrides[get_current_account_id] = lambda: "test-account"
    app.post("/api/v1/documents/manual", status_code=201, response_model=DocumentDetail)(create_document_with_manual_chunks)
    client = TestClient(app)

    res = client.post(
        "/api/v1/documents/manual",
        json={
            "dataset_id": str(dataset_id),
            "filename": "Manual Doc",
            "file_type": "md",
            "file_size": 42,
            "metadata": {"source": "manual"},
            "chunks": [
                {"content": "Clause 1", "page_number": 1, "start_char": 0, "end_char": 8, "metadata": {"kind": "text"}},
                {"content": "Clause 2", "page_number": 1, "start_char": 9, "end_char": 17, "metadata": {"kind": "text"}},
            ],
        },
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["status"] == "completed"
    assert body["dataset_id"] == str(dataset_id)
    assert body["chunk_count"] == 2
    assert body["metadata"]["pipeline_hash"] == "pipeline-hash-1"
    assert body["metadata"]["active_pipeline_ready"] is True

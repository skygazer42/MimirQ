from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.api.schemas.document import DocumentDetail
from app.core.database import get_db


class _DummyDB:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.commits = 0

    def add(self, obj) -> None:  # noqa: ANN001
        self.added.append(obj)

    def commit(self) -> None:
        self.commits += 1

    def refresh(self, obj) -> None:  # noqa: ANN001
        if getattr(obj, "chunk_count", None) is None:
            obj.chunk_count = 0
        if getattr(obj, "total_characters", None) is None:
            obj.total_characters = 0
        now = datetime.now(timezone.utc)
        if getattr(obj, "created_at", None) is None:
            obj.created_at = now
        if getattr(obj, "updated_at", None) is None:
            obj.updated_at = now
        return None


class _FakeRedis:
    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    async def set(self, key, value, ex=None, nx=False):  # noqa: ANN001, ANN202
        if nx and key in self._store:
            return False
        self._store[str(key)] = str(value)
        return True

    async def get(self, key):  # noqa: ANN001, ANN202
        return self._store.get(str(key))

    async def delete(self, key):  # noqa: ANN001, ANN202
        self._store.pop(str(key), None)


def test_concurrent_uploads_are_idempotent_via_lock(monkeypatch, tmp_path):  # noqa: ANN001
    import app.api.v1.documents as documents_module
    from app.api.v1.documents import upload_document
    from app.core.config import settings

    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path), raising=False)

    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()

    class _Dataset:
        def __init__(self, dataset_id: uuid.UUID):  # noqa: ANN001
            self.id = dataset_id
            self.dataset_metadata = {}

    monkeypatch.setattr(
        documents_module,
        "_resolve_writable_dataset",
        lambda *args, **kwargs: _Dataset(dataset_id),
        raising=True,
    )

    redis = _FakeRedis()

    async def _fake_get_queue():  # noqa: ANN202
        return redis

    monkeypatch.setattr("app.tasks.queue.get_queue", _fake_get_queue, raising=True)

    calls = {"enqueue": 0}

    async def _fake_enqueue(**kwargs):  # noqa: ANN001, ANN202
        calls["enqueue"] += 1
        return "task-123"

    monkeypatch.setattr(documents_module, "enqueue_document_processing", _fake_enqueue, raising=True)

    dummy_db = _DummyDB()

    def _override_get_db():  # noqa: ANN202
        yield dummy_db

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = lambda: tenant_id
    app.dependency_overrides[get_current_account_id] = lambda: "test-account"
    app.post("/api/v1/documents/upload", status_code=201, response_model=DocumentDetail)(upload_document)
    client = TestClient(app)

    payload = b"hello world"
    req = {
        "files": {"file": ("doc.txt", payload, "text/plain")},
        "data": {
            "dataset_id": str(dataset_id),
            "parser_backend": "auto",
            "chunk_strategy": "langchain_recursive",
        },
    }

    res1 = client.post("/api/v1/documents/upload", **req)
    assert res1.status_code == 201, res1.text

    # Simulate a concurrent duplicate: the second request should not enqueue another ingest job.
    res2 = client.post("/api/v1/documents/upload", **req)
    assert res2.status_code == 409, res2.text
    assert calls["enqueue"] == 1

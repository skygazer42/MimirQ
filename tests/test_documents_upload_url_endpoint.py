from __future__ import annotations

import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.core.database import get_db


class _DummyDB:
    def add(self, obj) -> None:  # noqa: ANN001
        return None

    def commit(self) -> None:
        return None

    def refresh(self, obj) -> None:  # noqa: ANN001
        return None


def _override_get_db():  # noqa: ANN202
    yield _DummyDB()


def _override_get_tenant_id() -> uuid.UUID:
    return uuid.uuid4()


def _override_get_current_account_id() -> str:
    return "test-account"


def test_documents_upload_url_happy_path(monkeypatch, tmp_path):  # noqa: ANN001
    from app.api.v1.documents import upload_document_from_url
    import app.api.v1.documents as documents_module
    from app.api.utils.url_ingest import DownloadedURL
    from app.core.config import settings

    monkeypatch.setattr(settings, "URL_INGEST_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path), raising=False)

    # Avoid SSRF/DNS logic in unit test.
    async def _ok_validate(url: str) -> str:  # noqa: ANN001
        return url

    async def _fake_download(url: str, destination, **kwargs):  # noqa: ANN001, ANN202
        payload = b"hello from url"
        destination.write_bytes(payload)
        return DownloadedURL(size_bytes=len(payload), content_type="text/plain", final_url=url)

    async def _fake_enqueue(**kwargs):  # noqa: ANN001, ANN202
        return "task-123"

    class _Dataset:
        def __init__(self, dataset_id: uuid.UUID):  # noqa: ANN001
            self.id = dataset_id
            self.dataset_metadata = {}

    dataset_id = uuid.uuid4()

    monkeypatch.setattr(documents_module, "validate_url_for_ingest", _ok_validate, raising=True)
    monkeypatch.setattr(documents_module, "download_url_to_path", _fake_download, raising=True)
    monkeypatch.setattr(documents_module, "enqueue_document_processing", _fake_enqueue, raising=True)
    monkeypatch.setattr(documents_module, "_resolve_writable_dataset", lambda *args, **kwargs: _Dataset(dataset_id), raising=True)

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = _override_get_tenant_id
    app.dependency_overrides[get_current_account_id] = _override_get_current_account_id
    app.post("/api/v1/documents/upload-url", status_code=201)(upload_document_from_url)
    client = TestClient(app)

    res = client.post(
        "/api/v1/documents/upload-url",
        json={
            "url": "https://example.com/doc.txt",
            "dataset_id": str(dataset_id),
            "filename": "doc.txt",
            "parser_backend": "auto",
            "chunk_strategy": "langchain_recursive",
            "pipeline": {
                "chunk_merge_small_min_chars": 200,
                "chunk_strategy_params": {"child_ratio": 0.25, "min_child_size": 300},
            },
        },
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body.get("status") == "pending"
    assert body.get("dataset_id") == str(dataset_id)
    meta = body.get("metadata") or {}
    assert meta.get("source_url") == "https://example.com/doc.txt"
    assert (meta.get("pipeline") or {}).get("chunk_merge_small_min_chars") == 200
    assert ((meta.get("pipeline") or {}).get("chunk_strategy_params") or {}).get("child_ratio") == 0.25

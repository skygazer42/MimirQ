
import uuid
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.api.schemas.document import DocumentDetail
from app.core.database import get_db
from tests.helpers.async_utils import yield_control


class _DummyDB:
    def add(self, obj) -> None:  # noqa: ANN001
        return None

    def commit(self) -> None:
        return None

    def refresh(self, obj) -> None:  # noqa: ANN001
        # Our unit test uses a dummy DB; mimic a few DB defaults needed by the response_model.
        if getattr(obj, "chunk_count", None) is None:
            obj.chunk_count = 0
        if getattr(obj, "total_characters", None) is None:
            obj.total_characters = 0
        now = datetime.now(UTC)
        if getattr(obj, "created_at", None) is None:
            obj.created_at = now
        if getattr(obj, "updated_at", None) is None:
            obj.updated_at = now
        return None


def _override_get_db():  # noqa: ANN202
    yield _DummyDB()


def _override_get_tenant_id() -> uuid.UUID:
    return uuid.uuid4()


def _override_get_current_account_id() -> str:
    return "test-account"


def test_documents_upload_url_happy_path(monkeypatch, tmp_path):  # noqa: ANN001
    import app.api.v1.documents as documents_module
    from app.api.utils.url_ingest import DownloadedURL
    from app.api.v1.documents import upload_document_from_url
    from app.core.config import settings

    monkeypatch.setattr(settings, "URL_INGEST_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path), raising=False)

    # Avoid SSRF/DNS logic in unit test.
    async def _ok_validate(url: str) -> str:  # noqa: ANN001
        await yield_control()
        return url

    async def _fake_download(url: str, destination, **kwargs):  # noqa: ANN001, ANN202
        await yield_control()
        payload = b"hello from url"
        destination.write_bytes(payload)
        return DownloadedURL(
            size_bytes=len(payload),
            content_type="text/plain",
            final_url=url,
            last_modified="Wed, 21 Oct 2015 07:28:00 GMT",
            etag="etag-123",
        )

    async def _fake_enqueue(**kwargs):  # noqa: ANN001, ANN202
        await yield_control()
        return "task-123"

    class _Dataset:
        def __init__(self, dataset_id: uuid.UUID):  # noqa: ANN001
            self.id = dataset_id
            self.dataset_metadata = {}

    dataset_id = uuid.uuid4()

    monkeypatch.setattr(documents_module, "validate_url_for_ingest", _ok_validate, raising=True)
    monkeypatch.setattr(documents_module, "download_url_to_path", _fake_download, raising=True)
    monkeypatch.setattr(documents_module, "enqueue_document_processing", _fake_enqueue, raising=True)
    monkeypatch.setattr(documents_module, "_resolve_writable_dataset", lambda *_args, **_kwargs: _Dataset(dataset_id), raising=True)

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = _override_get_tenant_id
    app.dependency_overrides[get_current_account_id] = _override_get_current_account_id
    # Mirror the real API contract: metadata should be exposed under `metadata` (alias of ORM `doc_metadata`).
    app.post("/api/v1/documents/upload-url", status_code=201, response_model=DocumentDetail)(upload_document_from_url)
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
    assert meta.get("source_last_modified_raw") == "Wed, 21 Oct 2015 07:28:00 GMT"
    assert meta.get("source_last_modified_source") == "http:last-modified"
    assert meta.get("source_last_modified_at") == "2015-10-21T07:28:00+00:00"
    assert meta.get("source_etag") == "etag-123"
    assert meta.get("content_sha256")
    assert isinstance(meta.get("source_fetched_at"), str) and meta.get("source_fetched_at")
    assert (meta.get("pipeline") or {}).get("chunk_merge_small_min_chars") == 200
    assert ((meta.get("pipeline") or {}).get("chunk_strategy_params") or {}).get("child_ratio") == pytest.approx(0.25)


def test_documents_upload_url_falls_back_when_last_modified_missing(monkeypatch, tmp_path):  # noqa: ANN001
    import app.api.v1.documents as documents_module
    from app.api.utils.url_ingest import DownloadedURL
    from app.api.v1.documents import upload_document_from_url
    from app.core.config import settings

    monkeypatch.setattr(settings, "URL_INGEST_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path), raising=False)

    async def _ok_validate(url: str) -> str:  # noqa: ANN001
        await yield_control()
        return url

    async def _fake_download(url: str, destination, **kwargs):  # noqa: ANN001, ANN202
        await yield_control()
        payload = b"hello from url"
        destination.write_bytes(payload)
        return DownloadedURL(size_bytes=len(payload), content_type="text/plain", final_url=url, etag="etag-456")

    async def _fake_enqueue(**kwargs):  # noqa: ANN001, ANN202
        await yield_control()
        return "task-123"

    class _Dataset:
        def __init__(self, dataset_id: uuid.UUID):  # noqa: ANN001
            self.id = dataset_id
            self.dataset_metadata = {}

    dataset_id = uuid.uuid4()

    monkeypatch.setattr(documents_module, "validate_url_for_ingest", _ok_validate, raising=True)
    monkeypatch.setattr(documents_module, "download_url_to_path", _fake_download, raising=True)
    monkeypatch.setattr(documents_module, "enqueue_document_processing", _fake_enqueue, raising=True)
    monkeypatch.setattr(documents_module, "_resolve_writable_dataset", lambda *_args, **_kwargs: _Dataset(dataset_id), raising=True)

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = _override_get_tenant_id
    app.dependency_overrides[get_current_account_id] = _override_get_current_account_id
    app.post("/api/v1/documents/upload-url", status_code=201, response_model=DocumentDetail)(upload_document_from_url)
    client = TestClient(app)

    res = client.post(
        "/api/v1/documents/upload-url",
        json={
            "url": "https://example.com/doc.txt",
            "dataset_id": str(dataset_id),
            "filename": "doc.txt",
            "parser_backend": "auto",
            "chunk_strategy": "langchain_recursive",
        },
    )
    assert res.status_code == 201, res.text
    meta = (res.json() or {}).get("metadata") or {}
    assert meta.get("source_last_modified_source") == "fallback:fetched_at"
    assert meta.get("source_last_modified_at") == meta.get("source_fetched_at")
    assert meta.get("source_last_modified_raw") is None
    assert meta.get("source_etag") == "etag-456"
    assert meta.get("content_sha256")


def test_documents_upload_url_rejects_unknown_pipeline_fields_with_422(monkeypatch, tmp_path):  # noqa: ANN001
    from app.api.v1.documents import upload_document_from_url
    from app.core.config import settings

    monkeypatch.setattr(settings, "URL_INGEST_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path), raising=False)

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = _override_get_tenant_id
    app.dependency_overrides[get_current_account_id] = _override_get_current_account_id
    app.post("/api/v1/documents/upload-url", status_code=201, response_model=DocumentDetail)(upload_document_from_url)
    client = TestClient(app)

    response = client.post(
        "/api/v1/documents/upload-url",
        json={
            "url": "https://example.com/doc.txt",
            "pipeline": {
                "chunk_size": 512,
                "unexpected_field": True,
            },
        },
    )

    assert response.status_code == 422, response.text

from __future__ import annotations

import uuid
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.documents import download_document
from app.core.config import settings
from app.core.database import get_db
from app.models.document import Document as DBDocument
from app.storage.object import minio as minio_mod


def test_download_document_minio_supports_range_and_conditional_caching(monkeypatch) -> None:
    monkeypatch.delenv("ENV", raising=False)
    monkeypatch.setattr(settings, "AUTH_MODE", "header", raising=False)
    monkeypatch.setattr(settings, "MINIO_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "MINIO_BUCKET_NAME", "mimirq", raising=False)
    monkeypatch.setattr(settings, "ASSET_CACHE_MAX_AGE_SEC", 3600, raising=False)

    tenant_id = uuid.UUID(str(settings.DEFAULT_TENANT_ID))
    document_id = uuid.uuid4()
    bucket = str(settings.MINIO_BUCKET_NAME)
    expected_object_name = minio_mod.minio_service.build_document_object_name(
        tenant_id=str(tenant_id),
        dataset_id=str(tenant_id),
        document_id=str(document_id),
        extension=".pdf",
    )

    data = b"0123456789"

    class _Stat:
        size = len(data)
        etag = "etag123"

    def _fake_stat_object(*, object_name: str):  # noqa: ANN001
        assert object_name == expected_object_name
        return _Stat()

    def _fake_iter_object_bytes(*, object_name: str, offset: int = 0, length=None, **_kw):  # noqa: ANN001
        assert object_name.endswith(".pdf")
        if length is None:
            yield data[int(offset or 0) :]
            return
        start = int(offset or 0)
        end = start + int(length or 0)
        yield data[start:end]

    monkeypatch.setattr(minio_mod.minio_service, "stat_object", _fake_stat_object, raising=True)
    monkeypatch.setattr(minio_mod.minio_service, "iter_object_bytes", _fake_iter_object_bytes, raising=True)

    doc = SimpleNamespace(
        id=document_id,
        tenant_id=tenant_id,
        dataset_id=None,
        filename="example.pdf",
        file_type="pdf",
        file_path=minio_mod.build_minio_uri(bucket, expected_object_name),
    )

    class _DummyQuery:
        def filter(self, *_args, **_kwargs):  # noqa: ANN001
            return self

        def first(self):  # noqa: ANN001
            return doc

    class _DummyDB:
        def query(self, model):  # noqa: ANN001
            assert model is DBDocument
            return _DummyQuery()

        def close(self) -> None:
            return None

        def rollback(self) -> None:
            return None

    def _override_get_db():  # noqa: ANN202
        yield _DummyDB()

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.get("/api/v1/documents/{document_id}/download")(download_document)
    client = TestClient(app)

    res = client.get(f"/api/v1/documents/{document_id}/download")
    assert res.status_code == 200, res.text
    assert res.headers.get("Accept-Ranges") == "bytes"
    cache_control = res.headers.get("Cache-Control") or ""
    assert cache_control.startswith("private, max-age=3600")
    assert res.headers.get("ETag")
    assert res.content == data

    res304 = client.get(
        f"/api/v1/documents/{document_id}/download",
        headers={"If-None-Match": res.headers.get("ETag") or ""},
    )
    assert res304.status_code == 304

    res2 = client.get(
        f"/api/v1/documents/{document_id}/download",
        headers={"Range": "bytes=0-3"},
    )
    assert res2.status_code == 206
    assert res2.headers.get("Content-Range") == f"bytes 0-3/{len(data)}"
    assert res2.headers.get("Content-Length") == "4"
    assert res2.content == b"0123"


def test_download_document_minio_is_not_cached_when_token_query_param_present(monkeypatch) -> None:
    monkeypatch.delenv("ENV", raising=False)
    monkeypatch.setattr(settings, "AUTH_MODE", "header", raising=False)
    monkeypatch.setattr(settings, "MINIO_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "MINIO_BUCKET_NAME", "mimirq", raising=False)
    monkeypatch.setattr(settings, "ASSET_CACHE_MAX_AGE_SEC", 3600, raising=False)

    tenant_id = uuid.UUID(str(settings.DEFAULT_TENANT_ID))
    document_id = uuid.uuid4()
    bucket = str(settings.MINIO_BUCKET_NAME)
    expected_object_name = minio_mod.minio_service.build_document_object_name(
        tenant_id=str(tenant_id),
        dataset_id=str(tenant_id),
        document_id=str(document_id),
        extension=".pdf",
    )

    data = b"0123456789"

    class _Stat:
        size = len(data)
        etag = "etag123"

    def _fake_stat_object(*, object_name: str):  # noqa: ANN001
        assert object_name == expected_object_name
        return _Stat()

    def _fake_iter_object_bytes(*, object_name: str, offset: int = 0, length=None, **_kw):  # noqa: ANN001
        assert object_name.endswith(".pdf")
        if length is None:
            yield data[int(offset or 0) :]
            return
        start = int(offset or 0)
        end = start + int(length or 0)
        yield data[start:end]

    monkeypatch.setattr(minio_mod.minio_service, "stat_object", _fake_stat_object, raising=True)
    monkeypatch.setattr(minio_mod.minio_service, "iter_object_bytes", _fake_iter_object_bytes, raising=True)

    doc = SimpleNamespace(
        id=document_id,
        tenant_id=tenant_id,
        dataset_id=None,
        filename="example.pdf",
        file_type="pdf",
        file_path=minio_mod.build_minio_uri(bucket, expected_object_name),
    )

    class _DummyQuery:
        def filter(self, *_args, **_kwargs):  # noqa: ANN001
            return self

        def first(self):  # noqa: ANN001
            return doc

    class _DummyDB:
        def query(self, model):  # noqa: ANN001
            assert model is DBDocument
            return _DummyQuery()

        def close(self) -> None:
            return None

        def rollback(self) -> None:
            return None

    def _override_get_db():  # noqa: ANN202
        yield _DummyDB()

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.get("/api/v1/documents/{document_id}/download")(download_document)
    client = TestClient(app)

    res = client.get(f"/api/v1/documents/{document_id}/download", params={"token": "dummy-token"})
    assert res.status_code == 200, res.text
    assert res.content == data
    assert res.headers.get("Cache-Control") == "no-store"
    assert res.headers.get("Pragma") == "no-cache"
    assert res.headers.get("Expires") == "0"

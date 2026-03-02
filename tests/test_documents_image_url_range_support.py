from __future__ import annotations

import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.documents import get_image_url
from app.core.config import settings
from app.core.database import get_db
from app.storage.object import minio as minio_mod


class _DummyDB:
    def close(self) -> None:
        return None

    def rollback(self) -> None:
        return None


def _override_get_db():  # noqa: ANN202
    yield _DummyDB()


def test_image_url_endpoint_proxies_minio_bytes_with_range(monkeypatch) -> None:
    # Ensure non-production behavior: allow anonymous asset access in AUTH_MODE=header.
    monkeypatch.delenv("ENV", raising=False)
    monkeypatch.setattr(settings, "AUTH_MODE", "header", raising=False)
    monkeypatch.setattr(settings, "MINIO_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "ASSET_CACHE_MAX_AGE_SEC", 3600, raising=False)

    # Legacy img_id format avoids DB document lookups.
    img_id = f"{uuid.uuid4().hex}-{uuid.uuid4().hex}"

    data = b"0123456789"

    class _Stat:
        size = len(data)
        etag = "etag123"

    def _fake_stat_object(*, object_name: str):  # noqa: ANN001
        assert object_name.endswith(".jpg")
        return _Stat()

    def _fake_iter_object_bytes(*, object_name: str, offset: int = 0, length=None, **_kw):  # noqa: ANN001
        assert object_name.endswith(".jpg")
        if length is None:
            yield data[int(offset or 0) :]
            return
        start = int(offset or 0)
        end = start + int(length or 0)
        yield data[start:end]

    monkeypatch.setattr(minio_mod.minio_service, "stat_object", _fake_stat_object, raising=True)
    monkeypatch.setattr(minio_mod.minio_service, "iter_object_bytes", _fake_iter_object_bytes, raising=True)

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.get("/api/v1/documents/image-url/{img_id}")(get_image_url)
    client = TestClient(app)

    # Full response: sets caching + ETag.
    res = client.get(f"/api/v1/documents/image-url/{img_id}")
    assert res.status_code == 200
    assert res.headers.get("Accept-Ranges") == "bytes"
    cache_control = res.headers.get("Cache-Control") or ""
    assert cache_control.startswith("private, max-age=3600")
    assert res.headers.get("ETag")
    assert res.content == data

    # Conditional GET (no Range): 304.
    res304 = client.get(
        f"/api/v1/documents/image-url/{img_id}",
        headers={"If-None-Match": res.headers.get("ETag") or ""},
    )
    assert res304.status_code == 304

    # Single-range support.
    res2 = client.get(f"/api/v1/documents/image-url/{img_id}", headers={"Range": "bytes=0-3"})
    assert res2.status_code == 206
    assert res2.headers.get("Content-Range") == f"bytes 0-3/{len(data)}"
    assert res2.headers.get("Content-Length") == "4"
    assert res2.content == b"0123"

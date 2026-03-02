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


def test_image_url_response_is_not_cached_when_token_query_param_present(monkeypatch) -> None:
    monkeypatch.delenv("ENV", raising=False)
    monkeypatch.setattr(settings, "MINIO_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "AUTH_MODE", "header", raising=False)
    monkeypatch.setattr(settings, "ASSET_CACHE_MAX_AGE_SEC", 3600, raising=False)

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

    dataset_part = uuid.uuid4().hex
    img_id = f"{dataset_part}-dummy"

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.get("/api/v1/documents/image-url/{img_id}")(get_image_url)

    client = TestClient(app)
    res = client.get(f"/api/v1/documents/image-url/{img_id}", params={"token": "dummy-token"})

    assert res.status_code == 200
    assert res.content == data
    assert res.headers.get("Cache-Control") == "no-store"
    assert res.headers.get("Pragma") == "no-cache"
    assert res.headers.get("Expires") == "0"

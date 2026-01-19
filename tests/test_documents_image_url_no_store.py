from __future__ import annotations

import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.documents import get_image_url
from app.core.config import settings
from app.core.database import get_db


class _DummyDB:
    def close(self) -> None:
        return None

    def rollback(self) -> None:
        return None


def _override_get_db():  # noqa: ANN202
    yield _DummyDB()


def test_image_url_redirect_is_not_cached(monkeypatch) -> None:
    monkeypatch.delenv("ENV", raising=False)
    monkeypatch.setattr(settings, "MINIO_ENABLED", True, raising=False)

    # Avoid touching real MinIO in unit tests.
    import app.api.v1.documents as docs_mod

    monkeypatch.setattr(docs_mod.minio_service, "get_image_url", lambda *_a, **_k: "http://example.local/img.jpg")

    dataset_part = uuid.uuid4().hex
    img_id = f"{dataset_part}-dummy"

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.get("/api/v1/documents/image-url/{img_id}")(get_image_url)

    client = TestClient(app)
    res = client.get(f"/api/v1/documents/image-url/{img_id}", follow_redirects=False)

    assert res.status_code == 302
    assert res.headers.get("Location") == "http://example.local/img.jpg"
    assert res.headers.get("Cache-Control") == "no-store"
    assert res.headers.get("Pragma") == "no-cache"
    assert res.headers.get("Expires") == "0"

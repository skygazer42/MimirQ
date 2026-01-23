from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.documents import get_image
from app.core.config import settings
from app.core.database import get_db


class _DummyDB:
    def close(self) -> None:
        return None

    def rollback(self) -> None:
        return None


def _override_get_db():  # noqa: ANN202
    yield _DummyDB()


def test_image_endpoint_sets_cache_headers_and_supports_etag(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("ENV", raising=False)
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path), raising=False)
    monkeypatch.setattr(settings, "ASSET_CACHE_MAX_AGE_SEC", 3600, raising=False)

    tenant_id = uuid.UUID(str(settings.DEFAULT_TENANT_ID))
    image_id = uuid.uuid4().hex
    images_dir = Path(settings.UPLOAD_DIR) / str(tenant_id) / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    (images_dir / f"{image_id}.jpg").write_bytes(b"fake image bytes")

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.get("/api/v1/documents/image/{image_id}")(get_image)

    client = TestClient(app)
    res = client.get(f"/api/v1/documents/image/{image_id}")

    assert res.status_code == 200
    cache_control = res.headers.get("Cache-Control") or ""
    assert cache_control.startswith("private, max-age=3600")
    assert "immutable" in cache_control
    assert res.headers.get("X-Content-Type-Options") == "nosniff"

    etag = res.headers.get("ETag")
    assert etag

    res2 = client.get(
        f"/api/v1/documents/image/{image_id}",
        headers={"If-None-Match": etag},
    )
    assert res2.status_code == 304

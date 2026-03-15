from __future__ import annotations

import uuid
from datetime import UTC

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


def _build_app() -> TestClient:
    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.get("/api/v1/documents/image-url/{img_id}")(get_image_url)
    return TestClient(app)


def test_image_url_requires_auth_in_jwt_mode(monkeypatch) -> None:
    monkeypatch.delenv("ENV", raising=False)
    monkeypatch.setattr(settings, "MINIO_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "AUTH_MODE", "jwt", raising=False)

    client = _build_app()

    dataset_part = uuid.uuid4().hex
    img_id = f"{dataset_part}-dummy"

    res = client.get(f"/api/v1/documents/image-url/{img_id}", follow_redirects=False)
    assert res.status_code == 401


def test_image_url_requires_x_user_id_in_production_header_mode(monkeypatch) -> None:
    monkeypatch.setenv("ENV", "production")
    monkeypatch.setattr(settings, "MINIO_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "AUTH_MODE", "header", raising=False)

    client = _build_app()

    dataset_part = uuid.uuid4().hex
    img_id = f"{dataset_part}-dummy"
    tenant_id = uuid.uuid4()

    res = client.get(f"/api/v1/documents/image-url/{img_id}?tenant_id={tenant_id}", follow_redirects=False)
    assert res.status_code == 401


def test_image_url_denies_tenant_mismatch_between_img_id_and_request(monkeypatch) -> None:
    monkeypatch.delenv("ENV", raising=False)
    monkeypatch.setattr(settings, "MINIO_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "AUTH_MODE", "header", raising=False)

    # Avoid touching real MinIO in unit tests.
    import app.api.v1.documents as docs_mod

    monkeypatch.setattr(docs_mod.minio_service, "get_image_url", lambda *_a, **_k: "http://example.local/img.jpg")

    client = _build_app()

    tenant_in_img = uuid.uuid4()
    other_tenant = uuid.uuid4()
    dataset_id = uuid.uuid4()
    document_id = uuid.uuid4()
    img_id = f"{tenant_in_img}:{dataset_id}:{document_id}:0"

    res = client.get(f"/api/v1/documents/image-url/{img_id}?tenant_id={other_tenant}", follow_redirects=False)
    assert res.status_code == 403


def test_image_url_allows_token_query_param_and_enforces_tenant_claim(monkeypatch) -> None:
    from datetime import datetime, timedelta

    from jose import jwt

    import app.api.v1.documents as docs_mod

    monkeypatch.delenv("ENV", raising=False)
    monkeypatch.setattr(settings, "MINIO_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "AUTH_MODE", "jwt", raising=False)
    monkeypatch.setattr(settings, "ALGORITHM", "HS256", raising=False)
    monkeypatch.setattr(settings, "SECRET_KEY", "k" * 40, raising=False)
    monkeypatch.setattr(settings, "SECRET_KEY_FALLBACKS", "", raising=False)

    monkeypatch.setattr(settings, "JWT_ISSUER", "", raising=False)
    monkeypatch.setattr(settings, "JWT_AUDIENCE", "", raising=False)

    monkeypatch.setattr(settings, "JWT_TENANT_CLAIM", "tenant_id", raising=False)
    monkeypatch.setattr(settings, "JWT_ENFORCE_TENANT_HEADER_MATCH", True, raising=False)

    # Avoid touching real MinIO / DB in unit tests.
    monkeypatch.setattr(docs_mod.DatasetService, "ensure_member", lambda *_a, **_k: None)
    monkeypatch.setattr(docs_mod.DatasetService, "get_dataset", lambda *_a, **_k: None)
    monkeypatch.setattr(docs_mod.DatasetService, "assert_dataset_readable", lambda *_a, **_k: None)

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

    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    img_id = f"{dataset_id.hex}-dummy"

    token = jwt.encode(
        {
            "sub": "user-1",
            "tenant_id": str(tenant_id),
            "exp": datetime.now(UTC) + timedelta(minutes=5),
        },
        settings.SECRET_KEY,
        algorithm="HS256",
    )

    client = _build_app()
    res = client.get(
        f"/api/v1/documents/image-url/{img_id}",
        params={"tenant_id": str(tenant_id), "token": token},
        follow_redirects=False,
    )
    assert res.status_code == 200
    assert res.content == data
    assert res.headers.get("Cache-Control") == "no-store"
    assert res.headers.get("Pragma") == "no-cache"
    assert res.headers.get("Expires") == "0"

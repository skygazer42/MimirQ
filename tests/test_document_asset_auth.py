import asyncio
import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request

from app.core.database import get_db


class _Query:
    def __init__(self, result: Any):
        self._result = result

    def filter(self, *args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        return self

    def first(self):  # noqa: ANN202
        return self._result


class _DB:
    def __init__(self, document: Any):
        self._document = document

    def query(self, _model):  # noqa: ANN001, ANN202
        return _Query(self._document)


def _build_request(*, query: str = "", headers: dict[str, str] | None = None) -> Request:
    raw_headers = [
        (name.lower().encode("latin-1"), value.encode("latin-1"))
        for name, value in (headers or {}).items()
    ]
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/v1/documents/asset",
        "query_string": query.encode("latin-1"),
        "headers": raw_headers,
    }
    return Request(scope)


def _build_download_client(document: Any) -> TestClient:
    from app.api.v1.document_assets import download_document

    def _override_get_db():  # noqa: ANN202
        yield _DB(document)

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.get("/api/v1/documents/{document_id}/download")(download_document)
    return TestClient(app)


def _build_image_client() -> TestClient:
    from app.api.v1.document_assets import get_image

    def _override_get_db():  # noqa: ANN202
        yield _DB(None)

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.get("/api/v1/documents/image/{image_id}")(get_image)
    return TestClient(app)


def _build_image_url_client() -> TestClient:
    from app.api.v1.document_assets import get_image_url

    def _override_get_db():  # noqa: ANN202
        yield _DB(None)

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.get("/api/v1/documents/image-url/{img_id}")(get_image_url)
    return TestClient(app)


@pytest.mark.parametrize("query_key", ["token", "access_token"])
def test_asset_request_rejects_query_bearer_promotion(monkeypatch, query_key):  # noqa: ANN001
    import app.api.v1.documents as documents_module
    from app.core.config import settings

    auth_calls: list[dict[str, Any]] = []

    async def _fake_auth(**kwargs):  # noqa: ANN003, ANN202
        auth_calls.append(kwargs)
        return "acct-123"

    tenant_id = uuid.uuid4()
    request = _build_request(query=f"tenant_id={tenant_id}&{query_key}=jwt-from-url")

    monkeypatch.setattr(settings, "AUTH_MODE", "jwt", raising=False)
    monkeypatch.setattr(documents_module, "get_current_account_id_from_headers", _fake_auth, raising=True)

    with pytest.raises(documents_module.HTTPException) as excinfo:
        asyncio.run(documents_module._resolve_account_id_for_asset_request(request, tenant_id=tenant_id))

    assert excinfo.value.status_code == 401
    assert auth_calls == []


def test_download_document_uses_header_auth_and_no_store_cache(monkeypatch, tmp_path):  # noqa: ANN001
    import app.api.v1.documents as documents_module
    from app.core.config import settings
    from app.services.dataset_service import DatasetService

    tenant_id = uuid.uuid4()
    document_id = uuid.uuid4()
    upload_root = tmp_path / str(tenant_id)
    upload_root.mkdir(parents=True)
    file_path = upload_root / "asset.txt"
    file_path.write_bytes(b"asset-bytes")

    auth_calls: list[dict[str, Any]] = []

    async def _fake_auth(**kwargs):  # noqa: ANN003, ANN202
        auth_calls.append(kwargs)
        return "acct-123"

    monkeypatch.setattr(settings, "AUTH_MODE", "jwt", raising=False)
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path), raising=False)
    monkeypatch.setattr(settings, "ASSET_CACHE_MAX_AGE_SEC", 600, raising=False)
    monkeypatch.setattr(documents_module, "get_current_account_id_from_headers", _fake_auth, raising=True)
    monkeypatch.setattr(DatasetService, "ensure_member", lambda *_args, **_kwargs: None, raising=True)
    monkeypatch.setattr(documents_module, "_assert_document_acl_readable", lambda *_args, **_kwargs: None, raising=True)

    client = _build_download_client(
        SimpleNamespace(
            id=document_id,
            tenant_id=tenant_id,
            dataset_id=None,
            file_path=str(file_path),
            filename="asset.txt",
            file_type="txt",
        )
    )

    response = client.get(
        f"/api/v1/documents/{document_id}/download?tenant_id={tenant_id}",
        headers={"Authorization": "Bearer header.jwt"},
    )

    assert response.status_code == 200, response.text
    assert response.content == b"asset-bytes"
    assert response.headers["cache-control"] == "private, no-store"
    assert "pragma" not in response.headers
    assert "expires" not in response.headers
    assert auth_calls == [
        {
            "authorization": "Bearer header.jwt",
            "x_user_id": None,
            "x_tenant_id": str(tenant_id),
        }
    ]


def test_get_image_uses_header_auth_and_no_store_cache(monkeypatch, tmp_path):  # noqa: ANN001
    import app.api.v1.documents as documents_module
    from app.core.config import settings
    from app.services.dataset_service import DatasetService

    tenant_id = uuid.uuid4()
    image_id = uuid.uuid4()
    image_dir = tmp_path / str(tenant_id) / "images"
    image_dir.mkdir(parents=True)
    image_path = image_dir / f"{image_id.hex}.png"
    image_path.write_bytes(b"\x89PNG\r\n\x1a\npng-data")

    auth_calls: list[dict[str, Any]] = []

    async def _fake_auth(**kwargs):  # noqa: ANN003, ANN202
        auth_calls.append(kwargs)
        return "acct-123"

    monkeypatch.setattr(settings, "AUTH_MODE", "jwt", raising=False)
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path), raising=False)
    monkeypatch.setattr(settings, "ASSET_CACHE_MAX_AGE_SEC", 600, raising=False)
    monkeypatch.setattr(documents_module, "get_current_account_id_from_headers", _fake_auth, raising=True)
    monkeypatch.setattr(DatasetService, "ensure_member", lambda *_args, **_kwargs: None, raising=True)

    client = _build_image_client()

    response = client.get(
        f"/api/v1/documents/image/{image_id}?tenant_id={tenant_id}",
        headers={"Authorization": "Bearer header.jwt"},
    )

    assert response.status_code == 200, response.text
    assert response.content.startswith(b"\x89PNG\r\n\x1a\n")
    assert response.headers["cache-control"] == "private, no-store"
    assert "pragma" not in response.headers
    assert "expires" not in response.headers
    assert auth_calls == [
        {
            "authorization": "Bearer header.jwt",
            "x_user_id": None,
            "x_tenant_id": str(tenant_id),
        }
    ]


def test_get_image_url_hides_object_storage_errors(monkeypatch):  # noqa: ANN001
    import app.api.v1.document_assets as document_assets
    import app.api.v1.documents as documents_module
    from app.core.config import settings
    from app.services.dataset_service import DatasetService

    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    chunk_id = uuid.uuid4()
    img_id = f"{dataset_id.hex}-{chunk_id}"
    logged: list[tuple[object, ...]] = []

    async def _fake_auth(**_kwargs):  # noqa: ANN202
        return "acct-123"

    monkeypatch.setattr(settings, "AUTH_MODE", "jwt", raising=False)
    monkeypatch.setattr(settings, "MINIO_ENABLED", True, raising=False)
    monkeypatch.setattr(documents_module, "get_current_account_id_from_headers", _fake_auth, raising=True)
    monkeypatch.setattr(DatasetService, "ensure_member", lambda *_args, **_kwargs: None, raising=True)
    monkeypatch.setattr(
        DatasetService,
        "get_dataset",
        lambda *_args, **_kwargs: SimpleNamespace(id=dataset_id, tenant_id=tenant_id),
        raising=True,
    )
    monkeypatch.setattr(DatasetService, "assert_dataset_readable", lambda *_args, **_kwargs: None, raising=True)
    monkeypatch.setattr(
        documents_module.minio_service,
        "stat_object",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("backend exploded")),
        raising=True,
    )
    monkeypatch.setattr(
        document_assets,
        "logger",
        SimpleNamespace(warning=lambda *args, **_kwargs: logged.append(args)),
        raising=True,
    )

    client = _build_image_url_client()
    response = client.get(
        f"/api/v1/documents/image-url/{img_id}?tenant_id={tenant_id}",
        headers={"Authorization": "Bearer header.jwt"},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": documents_module.IMAGE_NOT_FOUND_DETAIL}
    assert logged


def test_download_document_hides_object_storage_errors(monkeypatch):  # noqa: ANN001
    import app.api.v1.document_assets as document_assets
    import app.api.v1.documents as documents_module
    from app.core.config import settings
    from app.services.dataset_service import DatasetService

    tenant_id = uuid.uuid4()
    document_id = uuid.uuid4()
    logged: list[tuple[object, ...]] = []

    async def _fake_auth(**_kwargs):  # noqa: ANN202
        return "acct-123"

    expected_object = documents_module.minio_service.build_document_object_name(
        tenant_id=str(tenant_id),
        dataset_id=str(tenant_id),
        document_id=str(document_id),
        extension=".pdf",
    )

    monkeypatch.setattr(settings, "AUTH_MODE", "jwt", raising=False)
    monkeypatch.setattr(settings, "MINIO_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "MINIO_BUCKET_NAME", "bucket", raising=False)
    monkeypatch.setattr(documents_module, "get_current_account_id_from_headers", _fake_auth, raising=True)
    monkeypatch.setattr(DatasetService, "ensure_member", lambda *_args, **_kwargs: None, raising=True)
    monkeypatch.setattr(
        documents_module.minio_service,
        "stat_object",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("backend exploded")),
        raising=True,
    )
    monkeypatch.setattr(
        document_assets,
        "logger",
        SimpleNamespace(warning=lambda *args, **_kwargs: logged.append(args)),
        raising=True,
    )

    client = _build_download_client(
        SimpleNamespace(
            id=document_id,
            tenant_id=tenant_id,
            dataset_id=None,
            file_path=f"minio://bucket/{expected_object}",
            filename="asset.pdf",
            file_type="pdf",
        )
    )

    response = client.get(
        f"/api/v1/documents/{document_id}/download?tenant_id={tenant_id}",
        headers={"Authorization": "Bearer header.jwt"},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": documents_module.DOCUMENT_FILE_NOT_FOUND_DETAIL}
    assert logged
    assert logged[0][0] == "Document asset stat failed for %r: %r"
    assert logged[0][1] == expected_object[:200]
    assert logged[0][2] == "backend exploded"

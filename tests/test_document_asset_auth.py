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


class _ModelQuery:
    def __init__(self, results_by_model: dict[str, Any], model: Any):
        self._results_by_model = results_by_model
        self._model = model

    def filter(self, *args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        return self

    def first(self):  # noqa: ANN202
        value = self._results_by_model.get(getattr(self._model, "__name__", ""))
        if isinstance(value, list):
            return value[0] if value else None
        return value

    def all(self):  # noqa: ANN202
        value = self._results_by_model.get(getattr(self._model, "__name__", ""))
        if isinstance(value, list):
            return list(value)
        if value is None:
            return []
        return [value]


class _DBByModel:
    def __init__(self, results_by_model: dict[str, Any]):
        self._results_by_model = dict(results_by_model)

    def query(self, model):  # noqa: ANN001, ANN202
        return _ModelQuery(self._results_by_model, model)


def _build_request(*, query: str = "", headers: dict[str, str] | None = None) -> Request:
    raw_headers = [(name.lower().encode("latin-1"), value.encode("latin-1")) for name, value in (headers or {}).items()]
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


def _build_image_client_with_db(db_obj: Any) -> TestClient:
    from app.api.v1.document_assets import get_image

    def _override_get_db():  # noqa: ANN202
        yield db_obj

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


def test_asset_request_header_auth_requires_user_id_by_default(monkeypatch):  # noqa: ANN001
    import app.api.v1.documents as documents_module
    from app.core.config import settings

    tenant_id = uuid.uuid4()
    request = _build_request(query=f"tenant_id={tenant_id}")

    monkeypatch.setattr(settings, "AUTH_MODE", "header", raising=False)
    monkeypatch.setattr(settings, "ASSET_HEADER_AUTH_ALLOW_ANONYMOUS", False, raising=False)

    with pytest.raises(documents_module.HTTPException) as excinfo:
        asyncio.run(documents_module._resolve_account_id_for_asset_request(request, tenant_id=tenant_id))

    assert excinfo.value.status_code == 401
    assert excinfo.value.detail == "X-User-ID header required"


def test_asset_request_header_auth_allows_explicit_anonymous_opt_in(monkeypatch):  # noqa: ANN001
    import app.api.v1.documents as documents_module
    from app.core.config import settings

    tenant_id = uuid.uuid4()
    request = _build_request(query=f"tenant_id={tenant_id}")

    monkeypatch.setattr(settings, "AUTH_MODE", "header", raising=False)
    monkeypatch.setattr(settings, "ASSET_HEADER_AUTH_ALLOW_ANONYMOUS", True, raising=False)

    assert asyncio.run(documents_module._resolve_account_id_for_asset_request(request, tenant_id=tenant_id)) is None


@pytest.mark.parametrize(
    ("filename", "payload"),
    [
        ("asset.html", b"<html><script>alert(1)</script></html>"),
        ("asset.css", b"body{background:red}"),
        ("asset.js", b"alert(1)"),
        ("asset.svg", b"<svg xmlns='http://www.w3.org/2000/svg'></svg>"),
        ("asset.xml", b"<root/>"),
    ],
)
def test_download_document_forces_attachment_for_active_content(monkeypatch, tmp_path, filename, payload):  # noqa: ANN001
    import app.api.v1.documents as documents_module
    from app.core.config import settings
    from app.services.dataset_service import DatasetService

    tenant_id = uuid.uuid4()
    document_id = uuid.uuid4()
    upload_root = tmp_path / str(tenant_id)
    upload_root.mkdir(parents=True)
    file_path = upload_root / filename
    file_path.write_bytes(payload)

    async def _fake_auth(**_kwargs):  # noqa: ANN202
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
            filename=filename,
            file_type=filename.rsplit(".", 1)[-1],
        )
    )

    response = client.get(
        f"/api/v1/documents/{document_id}/download?tenant_id={tenant_id}",
        headers={"Authorization": "Bearer header.jwt"},
    )

    assert response.status_code == 200, response.text
    assert response.content == payload
    assert response.headers["content-disposition"].startswith("attachment;")
    assert response.headers["x-content-type-options"] == "nosniff"


def test_download_document_keeps_inline_for_safe_image_preview(monkeypatch, tmp_path):  # noqa: ANN001
    import app.api.v1.documents as documents_module
    from app.core.config import settings
    from app.services.dataset_service import DatasetService

    tenant_id = uuid.uuid4()
    document_id = uuid.uuid4()
    upload_root = tmp_path / str(tenant_id)
    upload_root.mkdir(parents=True)
    file_path = upload_root / "preview.png"
    file_path.write_bytes(b"\x89PNG\r\n\x1a\npng-data")

    async def _fake_auth(**_kwargs):  # noqa: ANN202
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
            filename="preview.png",
            file_type="png",
        )
    )

    response = client.get(
        f"/api/v1/documents/{document_id}/download?tenant_id={tenant_id}",
        headers={"Authorization": "Bearer header.jwt"},
    )

    assert response.status_code == 200, response.text
    assert response.content.startswith(b"\x89PNG\r\n\x1a\n")
    assert response.headers["content-disposition"].startswith("inline;")


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
    dataset_id = uuid.uuid4()
    document_id = uuid.uuid4()
    image_id = uuid.uuid4()
    image_dir = tmp_path / str(tenant_id) / "images"
    image_dir.mkdir(parents=True)
    image_path = image_dir / f"{image_id.hex}.png"
    image_path.write_bytes(b"\x89PNG\r\n\x1a\npng-data")
    (image_dir / f"{image_id.hex}.json").write_text(
        ('{"dataset_id":"%s","document_id":"%s","tenant_id":"%s"}' % (dataset_id, document_id, tenant_id)),
        encoding="utf-8",
    )

    auth_calls: list[dict[str, Any]] = []
    acl_calls: list[dict[str, Any]] = []

    async def _fake_auth(**kwargs):  # noqa: ANN003, ANN202
        auth_calls.append(kwargs)
        return "acct-123"

    def _fake_assert_document_acl_readable(_db, **kwargs):  # noqa: ANN001
        acl_calls.append(kwargs)

    monkeypatch.setattr(settings, "AUTH_MODE", "jwt", raising=False)
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path), raising=False)
    monkeypatch.setattr(settings, "ASSET_CACHE_MAX_AGE_SEC", 600, raising=False)
    monkeypatch.setattr(documents_module, "get_current_account_id_from_headers", _fake_auth, raising=True)
    monkeypatch.setattr(DatasetService, "ensure_member", lambda *_args, **_kwargs: None, raising=True)
    dataset = SimpleNamespace(id=dataset_id, tenant_id=tenant_id, owner_id="owner-1")
    document = SimpleNamespace(
        id=document_id,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        access_mode="inherit",
        owner_id="owner-1",
    )
    monkeypatch.setattr(DatasetService, "assert_dataset_readable", lambda *_args, **_kwargs: None, raising=True)
    monkeypatch.setattr(
        documents_module, "_assert_document_acl_readable", _fake_assert_document_acl_readable, raising=True
    )

    client = _build_image_client_with_db(_DBByModel({"Document": [document], "Dataset": [dataset]}))

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
    assert len(acl_calls) == 1


def test_download_document_rejects_spoofed_request_tenant_when_verified_jwt_tenant_exists(monkeypatch, tmp_path):  # noqa: ANN001
    import app.api.v1.documents as documents_module
    from app.core.config import settings
    from app.services.dataset_service import DatasetService

    jwt_tenant_id = uuid.uuid4()
    spoofed_tenant_id = uuid.uuid4()
    document_id = uuid.uuid4()
    upload_root = tmp_path / str(jwt_tenant_id)
    upload_root.mkdir(parents=True)
    file_path = upload_root / "asset.txt"
    file_path.write_bytes(b"asset-bytes")

    auth_calls: list[dict[str, Any]] = []

    async def _fake_auth(**kwargs):  # noqa: ANN003, ANN202
        auth_calls.append(kwargs)
        return "acct-123"

    async def _fake_preferred_tenant(_request):  # noqa: ANN202
        return jwt_tenant_id

    monkeypatch.setattr(settings, "AUTH_MODE", "jwt", raising=False)
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path), raising=False)
    monkeypatch.setattr(settings, "ASSET_CACHE_MAX_AGE_SEC", 600, raising=False)
    monkeypatch.setattr(documents_module, "get_current_account_id_from_headers", _fake_auth, raising=True)
    monkeypatch.setattr(documents_module, "_preferred_jwt_tenant_id", _fake_preferred_tenant, raising=True)
    monkeypatch.setattr(DatasetService, "ensure_member", lambda *_args, **_kwargs: None, raising=True)
    monkeypatch.setattr(documents_module, "_assert_document_acl_readable", lambda *_args, **_kwargs: None, raising=True)

    client = _build_download_client(
        SimpleNamespace(
            id=document_id,
            tenant_id=jwt_tenant_id,
            dataset_id=None,
            file_path=str(file_path),
            filename="asset.txt",
            file_type="txt",
        )
    )

    response = client.get(
        f"/api/v1/documents/{document_id}/download?tenant_id={spoofed_tenant_id}",
        headers={
            "Authorization": "Bearer header.jwt",
            "X-Tenant-ID": str(spoofed_tenant_id),
        },
    )

    assert response.status_code == 403, response.text
    assert response.json() == {"detail": "Asset access denied for this tenant"}
    assert auth_calls == []


def test_get_image_rejects_spoofed_request_tenant_when_verified_jwt_tenant_exists(monkeypatch, tmp_path):  # noqa: ANN001
    import app.api.v1.documents as documents_module
    from app.core.config import settings
    from app.services.dataset_service import DatasetService

    jwt_tenant_id = uuid.uuid4()
    spoofed_tenant_id = uuid.uuid4()
    image_id = uuid.uuid4()
    image_dir = tmp_path / str(jwt_tenant_id) / "images"
    image_dir.mkdir(parents=True)
    image_path = image_dir / f"{image_id.hex}.png"
    image_path.write_bytes(b"\x89PNG\r\n\x1a\npng-data")

    auth_calls: list[dict[str, Any]] = []

    async def _fake_auth(**kwargs):  # noqa: ANN003, ANN202
        auth_calls.append(kwargs)
        return "acct-123"

    async def _fake_preferred_tenant(_request):  # noqa: ANN202
        return jwt_tenant_id

    monkeypatch.setattr(settings, "AUTH_MODE", "jwt", raising=False)
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path), raising=False)
    monkeypatch.setattr(settings, "ASSET_CACHE_MAX_AGE_SEC", 600, raising=False)
    monkeypatch.setattr(documents_module, "get_current_account_id_from_headers", _fake_auth, raising=True)
    monkeypatch.setattr(documents_module, "_preferred_jwt_tenant_id", _fake_preferred_tenant, raising=True)
    monkeypatch.setattr(DatasetService, "ensure_member", lambda *_args, **_kwargs: None, raising=True)

    client = _build_image_client()

    response = client.get(
        f"/api/v1/documents/image/{image_id}?tenant_id={spoofed_tenant_id}",
        headers={
            "Authorization": "Bearer header.jwt",
            "X-Tenant-ID": str(spoofed_tenant_id),
        },
    )

    assert response.status_code == 403, response.text
    assert response.json() == {"detail": "Asset access denied for this tenant"}
    assert auth_calls == []


def test_get_image_fails_closed_without_preview_ownership_metadata(monkeypatch, tmp_path):  # noqa: ANN001
    import app.api.v1.documents as documents_module
    from app.core.config import settings
    from app.services.dataset_service import DatasetService

    tenant_id = uuid.uuid4()
    image_id = uuid.uuid4()
    image_dir = tmp_path / str(tenant_id) / "images"
    image_dir.mkdir(parents=True)
    (image_dir / f"{image_id.hex}.png").write_bytes(b"\x89PNG\r\n\x1a\npng-data")

    async def _fake_auth(**_kwargs):  # noqa: ANN202
        return "acct-123"

    monkeypatch.setattr(settings, "AUTH_MODE", "jwt", raising=False)
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path), raising=False)
    monkeypatch.setattr(documents_module, "get_current_account_id_from_headers", _fake_auth, raising=True)
    monkeypatch.setattr(DatasetService, "ensure_member", lambda *_args, **_kwargs: None, raising=True)

    client = _build_image_client()
    response = client.get(
        f"/api/v1/documents/image/{image_id}?tenant_id={tenant_id}",
        headers={"Authorization": "Bearer header.jwt"},
    )

    assert response.status_code == 404, response.text


def test_get_image_skips_legacy_lookup_when_preview_file_is_missing(monkeypatch, tmp_path):  # noqa: ANN001
    import app.api.v1.document_assets as document_assets
    import app.api.v1.documents as documents_module
    from app.core.config import settings
    from app.services.dataset_service import DatasetService

    tenant_id = uuid.uuid4()
    image_id = uuid.uuid4()

    async def _fake_auth(**_kwargs):  # noqa: ANN202
        return "acct-123"

    monkeypatch.setattr(settings, "AUTH_MODE", "jwt", raising=False)
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path), raising=False)
    monkeypatch.setattr(documents_module, "get_current_account_id_from_headers", _fake_auth, raising=True)
    monkeypatch.setattr(DatasetService, "ensure_member", lambda *_args, **_kwargs: None, raising=True)
    monkeypatch.setattr(
        document_assets,
        "find_legacy_preview_document_ids",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("legacy lookup should not run")),
        raising=True,
    )

    client = _build_image_client()
    response = client.get(
        f"/api/v1/documents/image/{image_id}?tenant_id={tenant_id}",
        headers={"Authorization": "Bearer header.jwt"},
    )

    assert response.status_code == 404, response.text


def test_get_image_recovers_legacy_binding_through_document_acl(monkeypatch, tmp_path):  # noqa: ANN001
    import json

    import app.api.v1.document_assets as document_assets
    import app.api.v1.documents as documents_module
    from app.core.config import settings
    from app.services.dataset_service import DatasetService

    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    document_id = uuid.uuid4()
    image_id = uuid.uuid4()
    image_dir = tmp_path / str(tenant_id) / "images"
    image_dir.mkdir(parents=True)
    (image_dir / f"{image_id.hex}.png").write_bytes(b"\x89PNG\r\n\x1a\npng-data")

    async def _fake_auth(**_kwargs):  # noqa: ANN202
        return "legacy-reader"

    document = SimpleNamespace(
        id=document_id,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        access_mode="inherit",
        owner_id="owner-1",
    )
    dataset = SimpleNamespace(id=dataset_id, tenant_id=tenant_id, owner_id="owner-1")
    acl_calls: list[str] = []

    monkeypatch.setattr(settings, "AUTH_MODE", "jwt", raising=False)
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path), raising=False)
    monkeypatch.setattr(documents_module, "get_current_account_id_from_headers", _fake_auth, raising=True)
    monkeypatch.setattr(DatasetService, "ensure_member", lambda *_args, **_kwargs: None, raising=True)
    monkeypatch.setattr(DatasetService, "assert_dataset_readable", lambda *_args, **_kwargs: None, raising=True)
    monkeypatch.setattr(
        documents_module,
        "_assert_document_acl_readable",
        lambda *_args, **_kwargs: acl_calls.append("checked"),
        raising=True,
    )
    monkeypatch.setattr(
        document_assets,
        "find_legacy_preview_document_ids",
        lambda *_args, **_kwargs: {document_id},
        raising=True,
    )

    client = _build_image_client_with_db(_DBByModel({"Document": [document], "Dataset": [dataset]}))
    response = client.get(
        f"/api/v1/documents/image/{image_id}?tenant_id={tenant_id}",
        headers={"Authorization": "Bearer header.jwt"},
    )

    assert response.status_code == 200, response.text
    assert acl_calls == ["checked"]
    assert json.loads((image_dir / f"{image_id.hex}.json").read_text(encoding="utf-8")) == {
        "tenant_id": str(tenant_id),
        "dataset_id": str(dataset_id),
        "document_id": str(document_id),
    }


def test_get_image_recovers_from_malformed_sidecar_via_exact_legacy_acl(monkeypatch, tmp_path):  # noqa: ANN001
    import json

    import app.api.v1.document_assets as document_assets
    import app.api.v1.documents as documents_module
    from app.core.config import settings
    from app.services.dataset_service import DatasetService

    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    document_id = uuid.uuid4()
    image_id = uuid.uuid4()
    image_dir = tmp_path / str(tenant_id) / "images"
    image_dir.mkdir(parents=True)
    (image_dir / f"{image_id.hex}.png").write_bytes(b"\x89PNG\r\n\x1a\npng-data")
    (image_dir / f"{image_id.hex}.json").write_text(
        json.dumps({"tenant_id": str(tenant_id), "dataset_id": str(dataset_id)}),
        encoding="utf-8",
    )

    async def _fake_auth(**_kwargs):  # noqa: ANN202
        return "legacy-reader"

    document = SimpleNamespace(
        id=document_id,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        access_mode="inherit",
        owner_id="owner-1",
    )
    dataset = SimpleNamespace(id=dataset_id, tenant_id=tenant_id, owner_id="owner-1")
    acl_calls: list[str] = []

    monkeypatch.setattr(settings, "AUTH_MODE", "jwt", raising=False)
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path), raising=False)
    monkeypatch.setattr(documents_module, "get_current_account_id_from_headers", _fake_auth, raising=True)
    monkeypatch.setattr(DatasetService, "ensure_member", lambda *_args, **_kwargs: None, raising=True)
    monkeypatch.setattr(DatasetService, "assert_dataset_readable", lambda *_args, **_kwargs: None, raising=True)
    monkeypatch.setattr(
        documents_module,
        "_assert_document_acl_readable",
        lambda *_args, **_kwargs: acl_calls.append("checked"),
        raising=True,
    )
    monkeypatch.setattr(
        document_assets,
        "find_legacy_preview_document_ids",
        lambda *_args, **_kwargs: {document_id},
        raising=True,
    )

    client = _build_image_client_with_db(_DBByModel({"Document": [document], "Dataset": [dataset]}))
    response = client.get(
        f"/api/v1/documents/image/{image_id}?tenant_id={tenant_id}",
        headers={"Authorization": "Bearer header.jwt"},
    )

    assert response.status_code == 200, response.text
    assert acl_calls == ["checked"]
    assert json.loads((image_dir / f"{image_id.hex}.json").read_text(encoding="utf-8")) == {
        "tenant_id": str(tenant_id),
        "dataset_id": str(dataset_id),
        "document_id": str(document_id),
    }


def test_get_image_selects_safe_multi_candidate_without_persisting_binding(monkeypatch, tmp_path):  # noqa: ANN001
    import json

    from fastapi import HTTPException

    import app.api.v1.document_assets as document_assets
    import app.api.v1.documents as documents_module
    from app.core.config import settings
    from app.services.dataset_service import DatasetService

    tenant_id = uuid.uuid4()
    denied_dataset_id = uuid.uuid4()
    allowed_dataset_id = uuid.uuid4()
    denied_document_id = uuid.uuid4()
    allowed_document_id = uuid.uuid4()
    image_id = uuid.uuid4()
    image_dir = tmp_path / str(tenant_id) / "images"
    image_dir.mkdir(parents=True)
    (image_dir / f"{image_id.hex}.png").write_bytes(b"\x89PNG\r\n\x1a\npng-data")
    malformed_sidecar = {"tenant_id": str(tenant_id), "dataset_id": str(allowed_dataset_id)}
    (image_dir / f"{image_id.hex}.json").write_text(json.dumps(malformed_sidecar), encoding="utf-8")

    async def _fake_auth(**_kwargs):  # noqa: ANN202
        return "legacy-reader"

    denied_document = SimpleNamespace(
        id=denied_document_id,
        tenant_id=tenant_id,
        dataset_id=denied_dataset_id,
        access_mode="inherit",
        owner_id="owner-1",
    )
    allowed_document = SimpleNamespace(
        id=allowed_document_id,
        tenant_id=tenant_id,
        dataset_id=allowed_dataset_id,
        access_mode="inherit",
        owner_id="owner-2",
    )
    denied_dataset = SimpleNamespace(id=denied_dataset_id, tenant_id=tenant_id, owner_id="owner-1")
    allowed_dataset = SimpleNamespace(id=allowed_dataset_id, tenant_id=tenant_id, owner_id="owner-2")
    acl_calls: list[uuid.UUID] = []

    def _fake_assert_dataset_readable(_db, dataset, account_id):  # noqa: ANN001
        if dataset.id == denied_dataset_id:
            raise HTTPException(status_code=404, detail=f"dataset denied for {account_id}")

    monkeypatch.setattr(settings, "AUTH_MODE", "jwt", raising=False)
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path), raising=False)
    monkeypatch.setattr(documents_module, "get_current_account_id_from_headers", _fake_auth, raising=True)
    monkeypatch.setattr(DatasetService, "ensure_member", lambda *_args, **_kwargs: None, raising=True)
    monkeypatch.setattr(DatasetService, "assert_dataset_readable", _fake_assert_dataset_readable, raising=True)
    monkeypatch.setattr(
        documents_module,
        "_assert_document_acl_readable",
        lambda *_args, **kwargs: acl_calls.append(kwargs["document"].id),
        raising=True,
    )
    monkeypatch.setattr(
        document_assets,
        "find_legacy_preview_document_ids",
        lambda *_args, **_kwargs: {denied_document_id, allowed_document_id},
        raising=True,
    )

    client = _build_image_client_with_db(
        _DBByModel(
            {
                "Document": [denied_document, allowed_document],
                "Dataset": [denied_dataset, allowed_dataset],
            }
        )
    )
    response = client.get(
        f"/api/v1/documents/image/{image_id}?tenant_id={tenant_id}",
        headers={"Authorization": "Bearer header.jwt"},
    )

    assert response.status_code == 200, response.text
    assert acl_calls == [allowed_document_id]
    assert json.loads((image_dir / f"{image_id.hex}.json").read_text(encoding="utf-8")) == malformed_sidecar


def test_get_image_enforces_parent_document_acl_from_preview_ownership_metadata(monkeypatch, tmp_path):  # noqa: ANN001
    import json

    import app.api.v1.documents as documents_module
    from app.core.config import settings
    from app.services.dataset_service import DatasetService

    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    document_id = uuid.uuid4()
    image_id = uuid.uuid4()
    image_dir = tmp_path / str(tenant_id) / "images"
    image_dir.mkdir(parents=True)
    (image_dir / f"{image_id.hex}.png").write_bytes(b"\x89PNG\r\n\x1a\npng-data")
    (image_dir / f"{image_id.hex}.json").write_text(
        json.dumps(
            {
                "tenant_id": str(tenant_id),
                "dataset_id": str(dataset_id),
                "document_id": str(document_id),
            }
        ),
        encoding="utf-8",
    )

    auth_calls: list[dict[str, Any]] = []
    acl_calls: list[dict[str, Any]] = []

    async def _fake_auth(**kwargs):  # noqa: ANN003, ANN202
        auth_calls.append(kwargs)
        return "acct-123"

    def _fake_assert_document_acl_readable(_db, **kwargs):  # noqa: ANN001
        acl_calls.append(kwargs)

    document = SimpleNamespace(
        id=document_id,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        access_mode="inherit",
        owner_id="owner-1",
    )
    dataset = SimpleNamespace(id=dataset_id, tenant_id=tenant_id, owner_id="owner-1")

    monkeypatch.setattr(settings, "AUTH_MODE", "jwt", raising=False)
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path), raising=False)
    monkeypatch.setattr(documents_module, "get_current_account_id_from_headers", _fake_auth, raising=True)
    monkeypatch.setattr(DatasetService, "ensure_member", lambda *_args, **_kwargs: None, raising=True)
    monkeypatch.setattr(DatasetService, "get_dataset", lambda *_args, **_kwargs: dataset, raising=True)
    monkeypatch.setattr(DatasetService, "assert_dataset_readable", lambda *_args, **_kwargs: None, raising=True)
    monkeypatch.setattr(
        documents_module, "_assert_document_acl_readable", _fake_assert_document_acl_readable, raising=True
    )

    client = _build_image_client_with_db(_DBByModel({"Document": document}))
    response = client.get(
        f"/api/v1/documents/image/{image_id}?tenant_id={tenant_id}",
        headers={"Authorization": "Bearer header.jwt"},
    )

    assert response.status_code == 200, response.text
    assert response.content.startswith(b"\x89PNG\r\n\x1a\n")
    assert auth_calls == [
        {
            "authorization": "Bearer header.jwt",
            "x_user_id": None,
            "x_tenant_id": str(tenant_id),
        }
    ]
    assert len(acl_calls) == 1
    assert acl_calls[0]["tenant_id"] == tenant_id
    assert acl_calls[0]["account_id"] == "acct-123"
    assert acl_calls[0]["document"] is document
    assert acl_calls[0]["dataset"] is dataset


def test_get_image_allows_only_the_account_that_created_an_ephemeral_preview(monkeypatch, tmp_path):  # noqa: ANN001
    import json

    import app.api.v1.documents as documents_module
    from app.core.config import settings
    from app.services.dataset_service import DatasetService

    tenant_id = uuid.uuid4()
    image_id = uuid.uuid4()
    image_dir = tmp_path / str(tenant_id) / "images"
    image_dir.mkdir(parents=True)
    (image_dir / f"{image_id.hex}.png").write_bytes(b"\x89PNG\r\n\x1a\npng-data")
    (image_dir / f"{image_id.hex}.json").write_text(
        json.dumps({"tenant_id": str(tenant_id), "account_id": "preview-owner"}),
        encoding="utf-8",
    )

    current_account = {"value": "preview-owner"}

    async def _fake_auth(**_kwargs):  # noqa: ANN202
        return current_account["value"]

    monkeypatch.setattr(settings, "AUTH_MODE", "jwt", raising=False)
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path), raising=False)
    monkeypatch.setattr(documents_module, "get_current_account_id_from_headers", _fake_auth, raising=True)
    monkeypatch.setattr(DatasetService, "ensure_member", lambda *_args, **_kwargs: None, raising=True)

    client = _build_image_client()
    url = f"/api/v1/documents/image/{image_id}?tenant_id={tenant_id}"

    assert client.get(url, headers={"Authorization": "Bearer owner.jwt"}).status_code == 200

    current_account["value"] = "other-account"
    assert client.get(url, headers={"Authorization": "Bearer other.jwt"}).status_code == 404


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


def test_get_image_url_rejects_img_tenant_that_conflicts_with_verified_jwt_tenant(monkeypatch):  # noqa: ANN001
    import app.api.v1.documents as documents_module
    from app.core.config import settings

    jwt_tenant_id = uuid.uuid4()
    img_tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    document_id = uuid.uuid4()
    auth_calls: list[dict[str, Any]] = []

    async def _fake_auth(**kwargs):  # noqa: ANN003, ANN202
        auth_calls.append(kwargs)
        return "acct-123"

    async def _fake_preferred_tenant(_request):  # noqa: ANN202
        return jwt_tenant_id

    monkeypatch.setattr(settings, "MINIO_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "AUTH_MODE", "jwt", raising=False)
    monkeypatch.setattr(documents_module, "_preferred_jwt_tenant_id", _fake_preferred_tenant, raising=True)
    monkeypatch.setattr(documents_module, "get_current_account_id_from_headers", _fake_auth, raising=True)

    client = _build_image_url_client()
    response = client.get(
        f"/api/v1/documents/image-url/{img_tenant_id}:{dataset_id}:{document_id}:chunk-1",
        headers={"Authorization": "Bearer header.jwt"},
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "Image access denied for this tenant"}
    assert auth_calls == []


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
            access_mode="all_team_members",
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


def test_download_document_supports_generic_object_storage_uri(monkeypatch):  # noqa: ANN001
    import app.api.v1.document_assets as document_assets
    import app.api.v1.documents as documents_module
    from app.core.config import settings
    from app.services.dataset_service import DatasetService

    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    document_id = uuid.uuid4()

    async def _fake_auth(**_kwargs):  # noqa: ANN202
        return "acct-123"

    class _Store:
        def stat_object(self, **_kwargs):  # noqa: ANN003, ANN202
            return SimpleNamespace(size=5, etag="etag-1")

        def iter_object_bytes(self, **_kwargs):  # noqa: ANN003, ANN202
            yield b"hello"

    monkeypatch.setattr(settings, "AUTH_MODE", "jwt", raising=False)
    monkeypatch.setattr(documents_module, "get_current_account_id_from_headers", _fake_auth, raising=True)
    monkeypatch.setattr(DatasetService, "ensure_member", lambda *_args, **_kwargs: None, raising=True)
    monkeypatch.setattr(
        DatasetService,
        "get_dataset",
        lambda *_args, **_kwargs: SimpleNamespace(id=dataset_id, tenant_id=tenant_id),
        raising=True,
    )
    monkeypatch.setattr(DatasetService, "assert_dataset_readable", lambda *_args, **_kwargs: None, raising=True)
    monkeypatch.setattr(documents_module, "_assert_document_acl_readable", lambda *_args, **_kwargs: None, raising=True)
    monkeypatch.setattr(
        document_assets,
        "resolve_document_object_reference",
        lambda *_args, **_kwargs: (_Store(), SimpleNamespace(bucket="bucket", object_name="documents/t/d/source.pdf")),
        raising=True,
    )

    client = _build_download_client(
        SimpleNamespace(
            id=document_id,
            tenant_id=tenant_id,
            dataset_id=dataset_id,
            access_mode="all_team_members",
            file_path="s3://bucket/documents/t/d/source.pdf",
            filename="asset.pdf",
            file_type="pdf",
            doc_metadata={"source_storage_backend": "object_storage", "source_storage_provider": "s3"},
        )
    )

    response = client.get(
        f"/api/v1/documents/{document_id}/download?tenant_id={tenant_id}",
        headers={"Authorization": "Bearer header.jwt"},
    )

    assert response.status_code == 200
    assert response.content == b"hello"
    assert response.headers["content-disposition"].startswith("inline;")


import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

import jwt
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies.tenant import get_tenant_id
from app.core.config import settings


def _build_app() -> FastAPI:
    app = FastAPI()

    @app.get("/tid")
    def tid(*, tenant_id: Annotated[uuid.UUID, Depends(get_tenant_id)]):  # noqa: B008
        return {"tenant_id": str(tenant_id)}

    return app


def _jwt_token(*, secret_key: str, sub: str, tenant_id: str) -> str:
    return jwt.encode(
        {
            "sub": sub,
            "tenant_id": tenant_id,
            "exp": datetime.now(UTC) + timedelta(minutes=5),
        },
        secret_key,
        algorithm="HS256",
    )


def test_tenant_dependency_cannot_disable_verified_jwt_tenant_binding(monkeypatch):
    monkeypatch.setenv("ENV", "production")

    monkeypatch.setattr(settings, "AUTH_MODE", "jwt", raising=False)
    monkeypatch.setattr(settings, "ALGORITHM", "HS256", raising=False)
    monkeypatch.setattr(settings, "JWT_ISSUER", "", raising=False)
    monkeypatch.setattr(settings, "JWT_AUDIENCE", "", raising=False)
    monkeypatch.setattr(settings, "JWT_TENANT_CLAIM", "tenant_id", raising=False)
    monkeypatch.setattr(settings, "JWT_ENFORCE_TENANT_HEADER_MATCH", False, raising=False)
    monkeypatch.setattr(settings, "TENANT_PREFER_JWT_TENANT", False, raising=False)

    secret_key = "k" * 40
    monkeypatch.setattr(settings, "SECRET_KEY", secret_key, raising=False)
    monkeypatch.setattr(settings, "SECRET_KEY_FALLBACKS", "", raising=False)

    jwt_tid = str(uuid.uuid4())
    header_tid = str(uuid.uuid4())
    token = _jwt_token(secret_key=secret_key, sub="u-1", tenant_id=jwt_tid)

    client = TestClient(_build_app())
    res = client.get("/tid", headers={"Authorization": f"Bearer {token}", "X-Tenant-ID": header_tid})
    assert res.status_code == 200
    assert res.json()["tenant_id"] == jwt_tid


def test_tenant_dependency_uses_header_when_no_jwt_tenant_claim_is_configured(monkeypatch):
    monkeypatch.setenv("ENV", "production")
    monkeypatch.setattr(settings, "AUTH_MODE", "jwt", raising=False)
    monkeypatch.setattr(settings, "JWT_TENANT_CLAIM", "", raising=False)
    monkeypatch.setattr(settings, "TENANT_PREFER_JWT_TENANT", False, raising=False)

    header_tid = str(uuid.uuid4())
    client = TestClient(_build_app())
    res = client.get("/tid", headers={"X-Tenant-ID": header_tid})

    assert res.status_code == 200
    assert res.json()["tenant_id"] == header_tid


def test_tenant_dependency_prefers_verified_jwt_tenant_when_enabled(monkeypatch):
    monkeypatch.setenv("ENV", "production")

    monkeypatch.setattr(settings, "AUTH_MODE", "jwt", raising=False)
    monkeypatch.setattr(settings, "ALGORITHM", "HS256", raising=False)
    monkeypatch.setattr(settings, "JWT_ISSUER", "", raising=False)
    monkeypatch.setattr(settings, "JWT_AUDIENCE", "", raising=False)
    monkeypatch.setattr(settings, "JWT_TENANT_CLAIM", "tenant_id", raising=False)
    monkeypatch.setattr(settings, "JWT_ENFORCE_TENANT_HEADER_MATCH", False, raising=False)
    monkeypatch.setattr(settings, "TENANT_PREFER_JWT_TENANT", True, raising=False)

    secret_key = "k" * 40
    monkeypatch.setattr(settings, "SECRET_KEY", secret_key, raising=False)
    monkeypatch.setattr(settings, "SECRET_KEY_FALLBACKS", "", raising=False)

    jwt_tid = str(uuid.uuid4())
    token = _jwt_token(secret_key=secret_key, sub="u-2", tenant_id=jwt_tid)

    # Spoofed header should be ignored when prefer is enabled.
    spoofed_header_tid = str(uuid.uuid4())

    client = TestClient(_build_app())
    res = client.get("/tid", headers={"Authorization": f"Bearer {token}", "X-Tenant-ID": spoofed_header_tid})
    assert res.status_code == 200
    assert res.json()["tenant_id"] == jwt_tid

    # When prefer is enabled, a verified JWT tenant can be used even without a tenant header.
    res2 = client.get("/tid", headers={"Authorization": f"Bearer {token}"})
    assert res2.status_code == 200
    assert res2.json()["tenant_id"] == jwt_tid


def test_scim_opaque_bearer_uses_tenant_header_without_jwt_decoding(monkeypatch):
    import app.api.v1.scim as scim_module

    monkeypatch.setenv("ENV", "production")
    monkeypatch.setattr(settings, "AUTH_MODE", "jwt", raising=False)
    monkeypatch.setattr(settings, "JWT_TENANT_CLAIM", "tenant_id", raising=False)
    monkeypatch.setattr(settings, "SCIM_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "SCIM_BEARER_TOKEN", "opaque-scim-token", raising=False)
    monkeypatch.setattr(settings, "SCIM_IP_ALLOWLIST_CIDRS", "", raising=False)

    tenant_id = uuid.uuid4()
    monkeypatch.setattr(settings, "SCIM_TENANT_ID", str(tenant_id), raising=False)
    captured: dict[str, object] = {}

    def _list_users(_db, *, tenant_id, skip, limit):  # noqa: ANN001
        captured.update(tenant_id=tenant_id, skip=skip, limit=limit)
        return 0, []

    def _fake_db():  # noqa: ANN202
        yield object()

    monkeypatch.setattr(scim_module, "_list_users", _list_users, raising=True)
    app = FastAPI()
    app.include_router(scim_module.router, prefix="/scim/v2")
    app.dependency_overrides[scim_module.get_db] = _fake_db

    response = TestClient(app).get(
        "/scim/v2/Users",
        headers={
            "Authorization": "Bearer opaque-scim-token",
            "X-Tenant-ID": str(tenant_id),
        },
    )

    assert response.status_code == 200, response.text
    assert captured["tenant_id"] == tenant_id

    wrong_tenant = TestClient(app).get(
        "/scim/v2/Users",
        headers={
            "Authorization": "Bearer opaque-scim-token",
            "X-Tenant-ID": str(uuid.uuid4()),
        },
    )
    assert wrong_tenant.status_code == 403

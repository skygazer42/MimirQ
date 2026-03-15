from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from jose import jwk, jwt

from app.api.dependencies.auth import get_current_account_id
from app.api.middleware.request_id import RequestIDMiddleware
from app.core.config import settings
from app.core.jwt_utils import create_access_token
from app.core.logging_config import get_request_context
from tests.helpers.async_utils import yield_control


def _build_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(RequestIDMiddleware)

    @app.get("/whoami")
    def whoami(*, account_id: Annotated[str, Depends(get_current_account_id)]):  # noqa: B008
        return {"account_id": account_id, "ctx": get_request_context()}

    return app


def test_jwt_secret_key_fallback_allows_key_rotation(monkeypatch):
    monkeypatch.setattr(settings, "AUTH_MODE", "jwt", raising=False)
    monkeypatch.setattr(settings, "ALGORITHM", "HS256", raising=False)
    monkeypatch.setattr(settings, "JWT_ISSUER", "", raising=False)
    monkeypatch.setattr(settings, "JWT_AUDIENCE", "", raising=False)

    new_key = "n" * 40
    old_key = "o" * 40
    monkeypatch.setattr(settings, "SECRET_KEY", new_key, raising=False)
    monkeypatch.setattr(settings, "SECRET_KEY_FALLBACKS", old_key, raising=False)

    token = jwt.encode(
        {"sub": "user-rotated", "exp": datetime.now(UTC) + timedelta(minutes=5)},
        old_key,
        algorithm="HS256",
    )

    client = TestClient(_build_app())
    res = client.get(
        "/whoami",
        headers={
            "Authorization": f"Bearer {token}",
            "X-User-ID": "spoofed-header-user",
            "X-Tenant-ID": "t-1",
            "X-Request-ID": "r-1",
        },
    )
    assert res.status_code == 200
    payload = res.json()
    assert payload["account_id"] == "user-rotated"
    assert payload["ctx"]["user_id"] == "user-rotated"
    assert payload["ctx"]["tenant_id"] == "t-1"
    assert payload["ctx"]["request_id"] == "r-1"


def test_jwt_issuer_audience_enforced_when_configured(monkeypatch):
    monkeypatch.setattr(settings, "AUTH_MODE", "jwt", raising=False)
    monkeypatch.setattr(settings, "ALGORITHM", "HS256", raising=False)

    secret_key = "k" * 40
    monkeypatch.setattr(settings, "SECRET_KEY", secret_key, raising=False)
    monkeypatch.setattr(settings, "SECRET_KEY_FALLBACKS", "", raising=False)
    monkeypatch.setattr(settings, "JWT_ISSUER", "https://issuer.example", raising=False)
    monkeypatch.setattr(settings, "JWT_AUDIENCE", "mimirq", raising=False)

    client = TestClient(_build_app())

    bad_token = jwt.encode(
        {"sub": "user-1", "exp": datetime.now(UTC) + timedelta(minutes=5)},
        secret_key,
        algorithm="HS256",
    )
    res = client.get("/whoami", headers={"Authorization": f"Bearer {bad_token}"})
    assert res.status_code == 401

    good_token, _expires_in = create_access_token("user-1", expires_minutes=5)
    res = client.get("/whoami", headers={"Authorization": f"Bearer {good_token}"})
    assert res.status_code == 200
    assert res.json()["account_id"] == "user-1"


def test_header_mode_binds_user_id_from_header(monkeypatch):
    monkeypatch.setattr(settings, "AUTH_MODE", "header", raising=False)

    client = TestClient(_build_app())
    res = client.get(
        "/whoami",
        headers={
            "X-User-ID": "header-user",
            "X-Tenant-ID": "t-2",
            "X-Request-ID": "r-2",
        },
    )
    assert res.status_code == 200
    payload = res.json()
    assert payload["account_id"] == "header-user"
    assert payload["ctx"]["user_id"] == "header-user"
    assert payload["ctx"]["tenant_id"] == "t-2"
    assert payload["ctx"]["request_id"] == "r-2"


def test_jwt_tenant_claim_header_match_enforced_when_enabled(monkeypatch):
    monkeypatch.setattr(settings, "AUTH_MODE", "jwt", raising=False)
    monkeypatch.setattr(settings, "ALGORITHM", "HS256", raising=False)
    monkeypatch.setattr(settings, "JWT_ISSUER", "", raising=False)
    monkeypatch.setattr(settings, "JWT_AUDIENCE", "", raising=False)

    secret_key = "k" * 40
    monkeypatch.setattr(settings, "SECRET_KEY", secret_key, raising=False)
    monkeypatch.setattr(settings, "SECRET_KEY_FALLBACKS", "", raising=False)

    monkeypatch.setattr(settings, "JWT_TENANT_CLAIM", "tenant_id", raising=False)
    monkeypatch.setattr(settings, "JWT_ENFORCE_TENANT_HEADER_MATCH", True, raising=False)

    tenant_id = "00000000-0000-0000-0000-000000000000"
    token = jwt.encode(
        {
            "sub": "user-tenant-1",
            "tenant_id": tenant_id,
            "exp": datetime.now(UTC) + timedelta(minutes=5),
        },
        secret_key,
        algorithm="HS256",
    )

    client = TestClient(_build_app())

    ok = client.get("/whoami", headers={"Authorization": f"Bearer {token}", "X-Tenant-ID": tenant_id})
    assert ok.status_code == 200
    payload = ok.json()
    assert payload["account_id"] == "user-tenant-1"
    assert payload["ctx"]["tenant_id"] == tenant_id

    mismatch = client.get(
        "/whoami",
        headers={
            "Authorization": f"Bearer {token}",
            "X-Tenant-ID": "11111111-1111-1111-1111-111111111111",
        },
    )
    assert mismatch.status_code == 401

    missing_header = client.get("/whoami", headers={"Authorization": f"Bearer {token}"})
    assert missing_header.status_code == 400


def test_jwt_tenant_enforcement_accepts_custom_tenant_header(monkeypatch):
    monkeypatch.setattr(settings, "TENANT_HEADER", "X-Workspace-ID", raising=False)
    monkeypatch.setattr(settings, "AUTH_MODE", "jwt", raising=False)
    monkeypatch.setattr(settings, "ALGORITHM", "HS256", raising=False)
    monkeypatch.setattr(settings, "JWT_ISSUER", "", raising=False)
    monkeypatch.setattr(settings, "JWT_AUDIENCE", "", raising=False)

    secret_key = "k" * 40
    monkeypatch.setattr(settings, "SECRET_KEY", secret_key, raising=False)
    monkeypatch.setattr(settings, "SECRET_KEY_FALLBACKS", "", raising=False)

    monkeypatch.setattr(settings, "JWT_TENANT_CLAIM", "tenant_id", raising=False)
    monkeypatch.setattr(settings, "JWT_ENFORCE_TENANT_HEADER_MATCH", True, raising=False)

    tenant_id = "00000000-0000-0000-0000-000000000000"
    token = jwt.encode(
        {
            "sub": "user-tenant-2",
            "tenant_id": tenant_id,
            "exp": datetime.now(UTC) + timedelta(minutes=5),
        },
        secret_key,
        algorithm="HS256",
    )

    client = TestClient(_build_app())
    ok = client.get("/whoami", headers={"Authorization": f"Bearer {token}", "X-Workspace-ID": tenant_id})
    assert ok.status_code == 200
    assert ok.json()["account_id"] == "user-tenant-2"


def test_jwt_jwks_verification_allows_rs256_tokens(monkeypatch):
    from app.core import jwt_verify

    # Ensure clean cache for this test run.
    jwt_verify._jwks_cache.clear()
    jwt_verify._jwks_locks.clear()

    monkeypatch.setattr(settings, "AUTH_MODE", "jwt", raising=False)
    monkeypatch.setattr(settings, "ALGORITHM", "RS256", raising=False)
    monkeypatch.setattr(settings, "JWT_ISSUER", "", raising=False)
    monkeypatch.setattr(settings, "JWT_AUDIENCE", "", raising=False)
    monkeypatch.setattr(settings, "JWT_TENANT_CLAIM", "", raising=False)
    monkeypatch.setattr(settings, "JWT_ENFORCE_TENANT_HEADER_MATCH", False, raising=False)

    # Still required for other app features/config validation; not used for RS256 verification here.
    monkeypatch.setattr(settings, "SECRET_KEY", "s" * 40, raising=False)
    monkeypatch.setattr(settings, "SECRET_KEY_FALLBACKS", "", raising=False)

    jwks_url = "https://idp.example/.well-known/jwks.json"
    monkeypatch.setattr(settings, "JWT_JWKS_URLS", jwks_url, raising=False)
    monkeypatch.setattr(settings, "JWT_JWKS_CACHE_TTL_SEC", 300, raising=False)
    monkeypatch.setattr(settings, "JWT_JWKS_MAX_STALE_SEC", 3600, raising=False)
    monkeypatch.setattr(settings, "JWT_JWKS_HTTP_TIMEOUT_SEC", 1.0, raising=False)

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )

    kid = "kid-1"
    jwk_key = jwk.construct(public_pem, algorithm="RS256").to_dict()
    jwk_key["kid"] = kid
    jwk_key["use"] = "sig"

    async def _fake_fetch(url: str):
        await yield_control()
        assert url == jwks_url
        return [dict(jwk_key)]

    monkeypatch.setattr(jwt_verify, "_fetch_jwks_keys", _fake_fetch, raising=True)

    token = jwt.encode(
        {"sub": "user-jwks", "exp": datetime.now(UTC) + timedelta(minutes=5)},
        private_pem,
        algorithm="RS256",
        headers={"kid": kid},
    )

    client = TestClient(_build_app())
    res = client.get("/whoami", headers={"Authorization": f"Bearer {token}", "X-Tenant-ID": "t-1"})
    assert res.status_code == 200
    payload = res.json()
    assert payload["account_id"] == "user-jwks"
    assert payload["ctx"]["user_id"] == "user-jwks"


def test_jwt_oidc_discovery_can_resolve_jwks_uri(monkeypatch):
    from app.core import jwt_verify

    # Ensure clean caches for this test run.
    jwt_verify._jwks_cache.clear()
    jwt_verify._jwks_locks.clear()
    jwt_verify._oidc_cache.clear()
    jwt_verify._oidc_locks.clear()

    monkeypatch.setattr(settings, "AUTH_MODE", "jwt", raising=False)
    monkeypatch.setattr(settings, "ALGORITHM", "RS256", raising=False)
    monkeypatch.setattr(settings, "JWT_AUDIENCE", "", raising=False)

    issuer = "https://idp.example/"
    monkeypatch.setattr(settings, "JWT_ISSUER", issuer, raising=False)

    monkeypatch.setattr(settings, "JWT_TENANT_CLAIM", "", raising=False)
    monkeypatch.setattr(settings, "JWT_ENFORCE_TENANT_HEADER_MATCH", False, raising=False)

    # Still required for other app features/config validation; not used for RS256 verification here.
    monkeypatch.setattr(settings, "SECRET_KEY", "s" * 40, raising=False)
    monkeypatch.setattr(settings, "SECRET_KEY_FALLBACKS", "", raising=False)

    monkeypatch.setattr(settings, "JWT_JWKS_URLS", "", raising=False)
    monkeypatch.setattr(settings, "JWT_JWKS_DISCOVERY_ENABLED", True, raising=False)

    jwks_url = "https://idp.example/.well-known/jwks.json"

    async def _fake_fetch_oidc(url: str):
        await yield_control()
        assert url == "https://idp.example/.well-known/openid-configuration"
        return {"jwks_uri": jwks_url}

    monkeypatch.setattr(jwt_verify, "_fetch_oidc_configuration", _fake_fetch_oidc, raising=True)

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )

    kid = "kid-2"
    jwk_key = jwk.construct(public_pem, algorithm="RS256").to_dict()
    jwk_key["kid"] = kid
    jwk_key["use"] = "sig"

    async def _fake_fetch_jwks(url: str):
        await yield_control()
        assert url == jwks_url
        return [dict(jwk_key)]

    monkeypatch.setattr(jwt_verify, "_fetch_jwks_keys", _fake_fetch_jwks, raising=True)

    token = jwt.encode(
        {
            "sub": "user-oidc",
            "iss": issuer,
            "exp": datetime.now(UTC) + timedelta(minutes=5),
        },
        private_pem,
        algorithm="RS256",
        headers={"kid": kid},
    )

    client = TestClient(_build_app())
    res = client.get("/whoami", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    assert res.json()["account_id"] == "user-oidc"

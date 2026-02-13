from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from jose import jwt

from app.api.dependencies.auth import get_current_account_id
from app.api.middleware.request_id import RequestIDMiddleware
from app.core.config import settings
from app.core.jwt_utils import create_access_token
from app.core.logging_config import get_request_context


def _build_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(RequestIDMiddleware)

    @app.get("/whoami")
    def whoami(account_id: str = Depends(get_current_account_id)):  # noqa: B008
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
        {"sub": "user-rotated", "exp": datetime.now(timezone.utc) + timedelta(minutes=5)},
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
        {"sub": "user-1", "exp": datetime.now(timezone.utc) + timedelta(minutes=5)},
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

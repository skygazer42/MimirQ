
from datetime import UTC, datetime
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import app.api.v1.auth as auth_module
from app.api.schemas.auth import SamlExchangeResponse, TokenResponse, UserPublic


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(auth_module.router, prefix="/auth")

    def _fake_db():
        yield object()

    app.dependency_overrides[auth_module.get_db] = _fake_db
    return app


def test_saml_exchange_endpoint_returns_auth_session(monkeypatch) -> None:
    user_id = uuid4()
    called: dict[str, object] = {}

    def _fake_exchange(*, db, provider_id, saml_response, relay_state=None, acs_url=None):  # noqa: ANN001
        called.update(
            {
                "provider_id": provider_id,
                "saml_response": saml_response,
                "relay_state": relay_state,
                "acs_url": acs_url,
            }
        )
        return SamlExchangeResponse(
            user=UserPublic(
                id=user_id,
                email="alice@example.com",
                username="alice",
                is_active=True,
                created_at=datetime.now(UTC),
                last_login_at=None,
            ),
            token=TokenResponse(access_token="jwt-token", expires_in=3600),
            return_to="/datasets/123",
        )

    monkeypatch.setattr(auth_module, "exchange_saml_response", _fake_exchange, raising=False)

    client = TestClient(_build_app())
    res = client.post(
        "/auth/saml/exchange",
        json={
            "provider_id": "default",
            "saml_response": "base64-response",
            "relay_state": "/datasets/123",
            "acs_url": "https://app.example.com/api/saml/acs",
        },
    )

    assert res.status_code == 200, res.text
    payload = res.json()
    assert payload["token"]["access_token"] == "jwt-token"
    assert payload["return_to"] == "/datasets/123"
    assert called["provider_id"] == "default"
    assert called["relay_state"] == "/datasets/123"


def test_saml_exchange_endpoint_surfaces_auth_errors(monkeypatch) -> None:
    def _boom(**_kwargs):  # noqa: ANN001
        raise HTTPException(status_code=401, detail="Invalid SAML signature")

    monkeypatch.setattr(auth_module, "exchange_saml_response", _boom, raising=False)

    client = TestClient(_build_app())
    res = client.post(
        "/auth/saml/exchange",
        json={
            "provider_id": "default",
            "saml_response": "base64-response",
        },
    )

    assert res.status_code == 401
    assert res.json()["detail"] == "Invalid SAML signature"

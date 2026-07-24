from datetime import datetime, timezone
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.api.v1.auth as auth_module
from app.api.schemas.auth import SamlExchangeResponse, TokenResponse, UserPublic
from app.services.saml_bridge_service import saml_bridge_session_from_exchange


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(auth_module.router, prefix="/auth")

    def _fake_db():
        yield object()

    app.dependency_overrides[auth_module.get_db] = _fake_db
    return app


def _sample_session(return_to: str = "/datasets/123") -> SamlExchangeResponse:
    return SamlExchangeResponse(
        user=UserPublic(
            id=uuid4(),
            email="alice@example.com",
            username="alice",
            is_active=True,
            created_at=datetime.now(timezone.utc),
            last_login_at=None,
        ),
        token=TokenResponse(access_token="jwt-token", expires_in=3600),
        return_to=return_to,
    )


def test_saml_exchange_endpoint_can_issue_bridge_code(monkeypatch) -> None:
    monkeypatch.setattr(auth_module, "exchange_saml_response", lambda **_kwargs: _sample_session(), raising=False)
    monkeypatch.setattr(auth_module, "issue_saml_bridge_session", lambda session: "bridge-code", raising=False)

    client = TestClient(_build_app())
    res = client.post(
        "/auth/saml/exchange",
        json={
            "provider_id": "default",
            "saml_response": "base64-response",
            "bridge_mode": True,
        },
    )

    assert res.status_code == 200, res.text
    payload = res.json()
    assert payload["bridge_code"] == "bridge-code"
    assert payload["token"]["access_token"] == "jwt-token"


def test_saml_bridge_consume_endpoint_returns_stored_session(monkeypatch) -> None:
    session = _sample_session("/graph")
    seen: dict[str, str] = {}

    def _consume(code: str):
        seen["code"] = code
        return saml_bridge_session_from_exchange(session)

    monkeypatch.setattr(auth_module, "consume_saml_bridge_session", _consume, raising=False)

    client = TestClient(_build_app())
    res = client.post("/auth/saml/bridge/consume", json={"code": "bridge-code"})

    assert res.status_code == 200, res.text
    assert res.json()["return_to"] == "/graph"
    assert seen == {"code": "bridge-code"}

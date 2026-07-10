
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import Depends, FastAPI, Request
from fastapi.testclient import TestClient
from jose import jwt

from app.api.dependencies.auth import get_current_account_id
from app.core.config import settings
from tests.helpers.async_utils import yield_control


def _build_app() -> FastAPI:
    app = FastAPI()

    @app.get("/state")
    async def state_endpoint(*, request: Request, account_id: Annotated[str, Depends(get_current_account_id)]):  # noqa: B008
        await yield_control()
        tenant_state = getattr(request.state, "tenant_id", None)
        return {
            "account_id": account_id,
            "state_user_id": getattr(request.state, "user_id", None),
            "state_tenant_id": str(tenant_state) if tenant_state is not None else None,
        }

    return app


def test_auth_dependency_sets_request_state_user_id_in_header_mode(monkeypatch):
    monkeypatch.setattr(settings, "AUTH_MODE", "header", raising=False)

    client = TestClient(_build_app())
    res = client.get("/state", headers={"X-User-ID": "header-user"})
    assert res.status_code == 200
    payload = res.json()

    assert payload["account_id"] == "header-user"
    assert payload["state_user_id"] == "header-user"
    # Header mode does not provide a verified tenant binding.
    assert payload["state_tenant_id"] is None


def test_auth_dependency_sets_request_state_user_and_tenant_in_jwt_mode(monkeypatch):
    monkeypatch.setattr(settings, "AUTH_MODE", "jwt", raising=False)
    monkeypatch.setattr(settings, "ALGORITHM", "HS256", raising=False)
    monkeypatch.setattr(settings, "JWT_ISSUER", "", raising=False)
    monkeypatch.setattr(settings, "JWT_AUDIENCE", "", raising=False)
    monkeypatch.setattr(settings, "JWT_ENFORCE_TENANT_HEADER_MATCH", False, raising=False)

    secret_key = "k" * 40
    monkeypatch.setattr(settings, "SECRET_KEY", secret_key, raising=False)
    monkeypatch.setattr(settings, "SECRET_KEY_FALLBACKS", "", raising=False)

    monkeypatch.setattr(settings, "JWT_TENANT_CLAIM", "tenant_id", raising=False)

    tenant_id = "00000000-0000-0000-0000-000000000000"
    token = jwt.encode(
        {"sub": "jwt-user", "tenant_id": tenant_id, "exp": datetime.now(UTC) + timedelta(minutes=5)},
        secret_key,
        algorithm="HS256",
    )

    client = TestClient(_build_app())
    res = client.get("/state", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    payload = res.json()

    assert payload["account_id"] == "jwt-user"
    assert payload["state_user_id"] == "jwt-user"
    assert payload["state_tenant_id"] == tenant_id


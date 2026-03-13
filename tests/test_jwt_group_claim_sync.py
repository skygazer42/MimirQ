from __future__ import annotations

import importlib
from datetime import datetime, timedelta, timezone
from typing import Annotated

import pytest
from fastapi import Depends, FastAPI, Request
from fastapi.testclient import TestClient
from jose import jwt

from app.api.dependencies.auth import get_current_account_id
from app.core.config import settings


def _import_or_fail(module: str):  # noqa: ANN001
    try:
        return importlib.import_module(module)
    except ModuleNotFoundError:
        pytest.fail(f"Expected module to exist: {module}")


def test_parse_groups_claim_caps_and_dedupes() -> None:
    mod = _import_or_fail("app.services.jwt_group_sync_service")
    if not hasattr(mod, "parse_group_names_from_jwt_payload"):
        pytest.fail("Expected parse_group_names_from_jwt_payload()")

    payload = {"groups": ["  Eng  ", "Eng", "", "HR", "HR", "x" * 300]}
    out = mod.parse_group_names_from_jwt_payload(payload, claim="groups", max_groups=2)
    assert out == ["Eng", "HR"]


def test_auth_dependency_calls_group_sync_when_enabled_and_throttled(monkeypatch: pytest.MonkeyPatch) -> None:
    mod = _import_or_fail("app.services.jwt_group_sync_service")
    if not hasattr(mod, "sync_jwt_groups_best_effort"):
        pytest.fail("Expected sync_jwt_groups_best_effort()")

    # Enable opt-in sync.
    monkeypatch.setattr(settings, "AUTH_MODE", "jwt", raising=False)
    monkeypatch.setattr(settings, "JWT_GROUPS_SYNC_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "JWT_GROUPS_CLAIM", "groups", raising=False)
    monkeypatch.setattr(settings, "JWT_GROUPS_MAX_GROUPS", 50, raising=False)
    monkeypatch.setattr(settings, "JWT_GROUPS_SYNC_TTL_SEC", 9999, raising=False)

    # JWT basics.
    monkeypatch.setattr(settings, "ALGORITHM", "HS256", raising=False)
    monkeypatch.setattr(settings, "JWT_ISSUER", "", raising=False)
    monkeypatch.setattr(settings, "JWT_AUDIENCE", "", raising=False)
    monkeypatch.setattr(settings, "JWT_ENFORCE_TENANT_HEADER_MATCH", False, raising=False)
    monkeypatch.setattr(settings, "JWT_TENANT_CLAIM", "tenant_id", raising=False)

    secret_key = "k" * 40
    monkeypatch.setattr(settings, "SECRET_KEY", secret_key, raising=False)
    monkeypatch.setattr(settings, "SECRET_KEY_FALLBACKS", "", raising=False)

    tenant_id = "00000000-0000-0000-0000-000000000000"
    token = jwt.encode(
        {"sub": "jwt-user", "tenant_id": tenant_id, "groups": ["Eng"], "exp": datetime.now(timezone.utc) + timedelta(minutes=5)},
        secret_key,
        algorithm="HS256",
    )

    calls: list[dict] = []

    def _fake_sync(*, tenant_id, account_id, jwt_payload):  # noqa: ANN001
        calls.append({"tenant_id": tenant_id, "account_id": account_id, "groups": jwt_payload.get("groups")})

    monkeypatch.setattr(mod, "sync_jwt_groups_best_effort", _fake_sync, raising=True)

    # Build app that exercises auth dependency.
    app = FastAPI()

    @app.get("/state")
    async def state_endpoint(request: Request, account_id: Annotated[str, Depends(get_current_account_id)]):  # noqa: B008
        return {"account_id": account_id, "tenant_id": str(getattr(request.state, "tenant_id", "") or "")}

    client = TestClient(app)
    res1 = client.get("/state", headers={"Authorization": f"Bearer {token}"})
    assert res1.status_code == 200
    res2 = client.get("/state", headers={"Authorization": f"Bearer {token}"})
    assert res2.status_code == 200

    # TTL throttle: only 1 sync call for same (tenant_id, user_id) within TTL.
    assert len(calls) == 1


def test_auth_dependency_never_blocks_on_group_sync_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    mod = _import_or_fail("app.services.jwt_group_sync_service")
    if not hasattr(mod, "sync_jwt_groups_best_effort"):
        pytest.fail("Expected sync_jwt_groups_best_effort()")

    monkeypatch.setattr(settings, "AUTH_MODE", "jwt", raising=False)
    monkeypatch.setattr(settings, "JWT_GROUPS_SYNC_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "JWT_GROUPS_SYNC_TTL_SEC", 0, raising=False)

    monkeypatch.setattr(settings, "ALGORITHM", "HS256", raising=False)
    monkeypatch.setattr(settings, "JWT_ISSUER", "", raising=False)
    monkeypatch.setattr(settings, "JWT_AUDIENCE", "", raising=False)
    monkeypatch.setattr(settings, "JWT_ENFORCE_TENANT_HEADER_MATCH", False, raising=False)
    monkeypatch.setattr(settings, "JWT_TENANT_CLAIM", "tenant_id", raising=False)

    secret_key = "k" * 40
    monkeypatch.setattr(settings, "SECRET_KEY", secret_key, raising=False)
    monkeypatch.setattr(settings, "SECRET_KEY_FALLBACKS", "", raising=False)

    tenant_id = "00000000-0000-0000-0000-000000000000"
    token = jwt.encode(
        {"sub": "jwt-user", "tenant_id": tenant_id, "groups": ["Eng"], "exp": datetime.now(timezone.utc) + timedelta(minutes=5)},
        secret_key,
        algorithm="HS256",
    )

    def _boom(**_kwargs):  # noqa: ANN001
        raise RuntimeError("boom")

    monkeypatch.setattr(mod, "sync_jwt_groups_best_effort", _boom, raising=True)

    app = FastAPI()

    @app.get("/state")
    async def state_endpoint(*, account_id: Annotated[str, Depends(get_current_account_id)]):  # noqa: B008
        return {"account_id": account_id}

    client = TestClient(app)
    res = client.get("/state", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200

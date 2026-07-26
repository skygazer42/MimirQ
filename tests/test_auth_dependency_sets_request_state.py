
import asyncio
import threading
from datetime import UTC, datetime, timedelta
from typing import Annotated

import jwt
import pytest
from fastapi import Depends, FastAPI, Request
from fastapi.testclient import TestClient

import app.api.dependencies.auth as auth_module
from app.api.dependencies.auth import get_current_account_id
from app.core.config import settings
from app.core.logging_config import get_request_context
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


@pytest.mark.asyncio
async def test_optional_jwt_db_work_runs_off_event_loop_and_is_awaited(monkeypatch):
    tenant_id = "00000000-0000-0000-0000-000000000000"
    monkeypatch.setattr(settings, "AUTH_MODE", "jwt", raising=False)
    monkeypatch.setattr(settings, "JWT_TENANT_CLAIM", "tenant_id", raising=False)
    monkeypatch.setattr(settings, "JWT_ENFORCE_TENANT_HEADER_MATCH", False, raising=False)
    monkeypatch.setattr(settings, "JWT_GROUPS_SYNC_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "JWT_TENANT_MEMBER_AUTO_PROVISION_ENABLED", True, raising=False)

    async def fake_decode(*, token, request):  # noqa: ANN001, ANN202, ARG001
        return {"sub": "jwt-user", "tenant_id": tenant_id}

    worker_started = threading.Event()
    release_worker = threading.Event()
    worker_thread_ids: list[int] = []
    worker_contexts: list[dict[str, str]] = []
    calls: list[str] = []

    def fake_group_sync(**kwargs):  # noqa: ANN003, ANN202, ARG001
        calls.append("groups")
        worker_thread_ids.append(threading.get_ident())
        worker_contexts.append(get_request_context())
        worker_started.set()
        release_worker.wait(timeout=1)

    def fake_auto_provision(**kwargs):  # noqa: ANN003, ANN202, ARG001
        calls.append("provision")
        worker_thread_ids.append(threading.get_ident())
        worker_contexts.append(get_request_context())

    monkeypatch.setattr(auth_module, "_decode_or_cached_jwt_payload", fake_decode)
    monkeypatch.setattr(auth_module, "_maybe_sync_jwt_groups", fake_group_sync)
    monkeypatch.setattr(auth_module, "_maybe_auto_provision_tenant_member", fake_auto_provision)

    event_loop_thread_id = threading.get_ident()
    auth_task = asyncio.create_task(
        auth_module.get_current_account_id_from_headers(
            authorization="Bearer token",
            x_user_id=None,
            x_tenant_id=None,
        )
    )
    try:
        assert await asyncio.to_thread(worker_started.wait, 1)
        assert not auth_task.done()
    finally:
        release_worker.set()

    assert await auth_task == "jwt-user"
    assert calls == ["groups", "provision"]
    assert set(worker_thread_ids).isdisjoint({event_loop_thread_id})
    assert [(context["tenant_id"], context["user_id"]) for context in worker_contexts] == [
        (tenant_id, "jwt-user"),
        (tenant_id, "jwt-user"),
    ]

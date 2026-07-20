import asyncio
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from starlette.requests import Request
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from app.api.dependencies.auth import _best_effort_client_ip
from app.api.middleware.rate_limit import _client_ip_from_request
from app.api.v1 import scim
from app.api.v1 import settings as settings_api
from app.core.config import settings


def test_client_ip_helpers_ignore_untrusted_forwarding_headers() -> None:
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [(b"x-forwarded-for", b"127.0.0.1"), (b"x-real-ip", b"127.0.0.1")],
            "client": ("203.0.113.10", 1234),
        }
    )

    assert _client_ip_from_request(request) == "203.0.113.10"
    assert _best_effort_client_ip(request) == "203.0.113.10"
    assert str(scim._extract_client_ip(request)) == "203.0.113.10"


def test_proxy_headers_only_replace_client_for_trusted_proxy() -> None:
    captured_clients: list[tuple[str, int] | None] = []

    async def app(scope, _receive, _send) -> None:  # noqa: ANN001
        captured_clients.append(scope.get("client"))

    middleware = ProxyHeadersMiddleware(app, trusted_hosts=["172.30.0.10"])

    async def invoke(proxy_ip: str) -> None:
        await middleware(
            {
                "type": "http",
                "headers": [(b"x-forwarded-for", b"203.0.113.20")],
                "client": (proxy_ip, 1234),
            },
            None,
            None,
        )

    asyncio.run(invoke("172.30.0.10"))
    asyncio.run(invoke("198.51.100.8"))

    assert captured_clients == [("203.0.113.20", 0), ("198.51.100.8", 1234)]


def test_global_settings_write_requires_default_tenant_owner(monkeypatch) -> None:
    default_tenant_id = uuid4()
    monkeypatch.setattr(settings, "DEFAULT_TENANT_ID", str(default_tenant_id), raising=False)
    monkeypatch.setattr(
        settings_api,
        "ensure_tenant_permission",
        lambda *_args, **_kwargs: SimpleNamespace(role="admin"),
    )

    with pytest.raises(HTTPException) as wrong_tenant:
        settings_api._ensure_settings_writable(object(), uuid4(), "admin")
    assert wrong_tenant.value.status_code == 403

    with pytest.raises(HTTPException) as admin:
        settings_api._ensure_settings_writable(object(), default_tenant_id, "admin")
    assert admin.value.status_code == 403

    monkeypatch.setattr(
        settings_api,
        "ensure_tenant_permission",
        lambda *_args, **_kwargs: SimpleNamespace(role="owner"),
    )
    settings_api._ensure_settings_writable(object(), default_tenant_id, "owner")


def test_scim_create_user_maps_membership_unique_race_to_conflict(monkeypatch) -> None:
    tenant_id = uuid4()

    class Database:
        rolled_back = False

        def add(self, _member: object) -> None:
            pass

        def commit(self) -> None:
            raise IntegrityError("insert", {}, RuntimeError("unique constraint"))

        def rollback(self) -> None:
            self.rolled_back = True

    database = Database()
    monkeypatch.setattr(settings, "SCIM_USERS_CREATE_ENABLED", True, raising=False)
    monkeypatch.setattr(scim, "_get_user", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(scim, "_audit_scim", lambda *_args, **_kwargs: None)

    response = scim.create_user(
        {"userName": "same-user"},
        None,
        tenant_id=tenant_id,
        actor_id="system:scim",
        db=database,
    )

    assert response.status_code == 409
    assert json.loads(response.body)["scimType"] == "uniqueness"
    assert database.rolled_back is True

import asyncio
import json
from types import SimpleNamespace
from uuid import uuid4

import httpx
import langchain_openai
import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from starlette.requests import Request
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from app.api.dependencies.auth import _best_effort_client_ip
from app.api.middleware.rate_limit import _client_ip_from_request
from app.api.utils import url_ingest
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


def test_llm_api_base_rejects_hostname_resolving_to_private_ip(monkeypatch: pytest.MonkeyPatch) -> None:
    async def resolve(_host: str, _port: int) -> list[str]:
        return ["172.18.0.7"]

    monkeypatch.setattr(url_ingest, "_resolve_host_ips", resolve)
    monkeypatch.setattr(settings, "URL_INGEST_ALLOW_PRIVATE_IPS", False, raising=False)

    with pytest.raises(HTTPException, match="api_base host not allowed"):
        asyncio.run(settings_api._validate_public_base_url("http://minio:9000/v1"))


def test_llm_api_base_allows_public_hostname(monkeypatch: pytest.MonkeyPatch) -> None:
    async def resolve(_host: str, _port: int) -> list[str]:
        return ["93.184.216.34"]

    monkeypatch.setattr(url_ingest, "_resolve_host_ips", resolve)
    monkeypatch.setattr(settings, "URL_INGEST_ALLOW_PRIVATE_IPS", False, raising=False)

    target = asyncio.run(settings_api._validate_public_base_url("https://example.com/v1"))
    assert target.connect_url == "https://93.184.216.34:443/v1"


def test_llm_api_base_rejects_resolution_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    async def resolve(_host: str, _port: int) -> list[str]:
        raise HTTPException(status_code=400, detail="failed to resolve url host")

    monkeypatch.setattr(url_ingest, "_resolve_host_ips", resolve)
    monkeypatch.setattr(settings, "URL_INGEST_ALLOW_PRIVATE_IPS", False, raising=False)

    with pytest.raises(HTTPException, match="failed to resolve api_base host"):
        asyncio.run(settings_api._validate_public_base_url("https://missing.example/v1"))


def test_llm_api_base_rejects_mixed_public_and_private_dns_answers(monkeypatch: pytest.MonkeyPatch) -> None:
    async def resolve(_host: str, _port: int) -> list[str]:
        return ["93.184.216.34", "127.0.0.1"]

    monkeypatch.setattr(url_ingest, "_resolve_host_ips", resolve)
    monkeypatch.setattr(settings, "URL_INGEST_ALLOW_PRIVATE_IPS", False, raising=False)

    with pytest.raises(HTTPException, match="api_base host not allowed"):
        asyncio.run(settings_api._validate_public_base_url("https://example.com/v1"))


@pytest.mark.parametrize(
    ("api_base", "allowed"),
    [
        ("https://93.184.216.34/v1", True),
        ("http://127.0.0.1:8000/v1", False),
    ],
)
def test_llm_api_base_checks_literal_ips(
    api_base: str,
    allowed: bool,
) -> None:
    if allowed:
        target = asyncio.run(settings_api._validate_public_base_url(api_base))
        assert target.connect_url == "https://93.184.216.34:443/v1"
        return

    with pytest.raises(HTTPException, match="api_base host not allowed"):
        asyncio.run(settings_api._validate_public_base_url(api_base))


def test_llm_api_base_respects_explicit_private_ip_override(monkeypatch: pytest.MonkeyPatch) -> None:
    async def resolve(_host: str, _port: int) -> list[str]:
        return ["172.18.0.7"]

    monkeypatch.setattr(url_ingest, "_resolve_host_ips", resolve)
    monkeypatch.setattr(settings, "URL_INGEST_ALLOW_PRIVATE_IPS", True, raising=False)

    target = asyncio.run(settings_api._validate_public_base_url("http://minio:9000/v1"))
    assert target.connect_url == "http://172.18.0.7:9000/v1"


def test_llm_test_passes_pinned_base_url_and_host_sni_to_chatopenai(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}
    validated_target = settings_api._ValidatedFetchTarget(
        raw="https://api.example.com/v1",
        connect_url="https://93.184.216.34:443/v1",
        host="api.example.com",
        host_header="api.example.com:443",
    )

    async def validate(base_url: str, *, enforce_allowlists: bool = True) -> object:
        captured["validated_args"] = (base_url, enforce_allowlists)
        return validated_target

    class FakeChatOpenAI:
        def __init__(self, **kwargs: object) -> None:
            captured["llm_kwargs"] = kwargs

        async def ainvoke(self, _messages: object) -> object:
            return SimpleNamespace(content="1")

    monkeypatch.setattr(settings_api, "_validated_fetch_target", validate)
    monkeypatch.setattr(settings_api, "_ensure_settings_writable", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(langchain_openai, "ChatOpenAI", FakeChatOpenAI)

    response = asyncio.run(
        settings_api.test_llm_connection(
            settings_api.TestLLMRequest(
                api_key="test-key",
                api_base="https://api.example.com/v1/chat/completions",
                model="gpt-test",
            ),
            tenant_id=uuid4(),
            account_id="owner",
            db=object(),
        )
    )

    assert response == {"success": True, "message": "1"}
    assert captured["validated_args"] == ("https://api.example.com/v1", False)
    llm_kwargs = captured["llm_kwargs"]
    assert llm_kwargs["base_url"] == "https://93.184.216.34:443/v1"
    assert llm_kwargs["http_client"].follow_redirects is False
    assert llm_kwargs["http_async_client"].follow_redirects is False

    sync_request = httpx.Request("POST", "https://93.184.216.34:443/v1/chat/completions")
    llm_kwargs["http_client"].event_hooks["request"][0](sync_request)
    assert sync_request.headers["Host"] == "api.example.com:443"
    assert sync_request.extensions["sni_hostname"] == "api.example.com"

    async_request = httpx.Request("POST", "https://93.184.216.34:443/v1/chat/completions")
    asyncio.run(llm_kwargs["http_async_client"].event_hooks["request"][0](async_request))
    assert async_request.headers["Host"] == "api.example.com:443"
    assert async_request.extensions["sni_hostname"] == "api.example.com"


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

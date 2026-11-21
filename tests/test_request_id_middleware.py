import re

import pytest

_UUID_HEX_RE = re.compile(r"^[0-9a-f]{32}$")


def test_normalize_request_id_accepts_valid() -> None:
    from app.api.middleware.request_context import _normalize_request_id

    assert _normalize_request_id("abc-123") == "abc-123"
    assert _normalize_request_id("  abc_123  ") == "abc_123"
    assert _normalize_request_id("a" * 128) == "a" * 128


def test_normalize_request_id_rejects_injection_and_invalid() -> None:
    from app.api.middleware.request_context import _normalize_request_id

    assert _UUID_HEX_RE.match(_normalize_request_id(None))
    assert _UUID_HEX_RE.match(_normalize_request_id(""))

    # Header injection / control chars
    assert _UUID_HEX_RE.match(_normalize_request_id("abc\n123"))
    assert _UUID_HEX_RE.match(_normalize_request_id("abc\r123"))

    # Invalid leading char
    assert _UUID_HEX_RE.match(_normalize_request_id("-bad"))

    # Too long (max 128)
    assert _UUID_HEX_RE.match(_normalize_request_id("a" * 129))


def test_request_context_does_not_take_identity_from_headers(monkeypatch) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api.middleware.request_context import RequestContextMiddleware as RequestIDMiddleware
    from app.infrastructure.config import settings
    from app.infrastructure.observability.logging import get_request_context

    monkeypatch.setattr(settings, "AUTH_MODE", "header")
    app = FastAPI()
    app.add_middleware(RequestIDMiddleware)

    @app.get("/")
    async def read() -> dict:
        return get_request_context()

    with TestClient(app) as client:
        response = client.get("/", headers={"X-Request-ID": "real-id", "X-User-ID": "forged", "X-Tenant-ID": "forged"})

    assert response.headers["X-Request-ID"] == "real-id"
    assert response.json()["request_id"] == "real-id"
    assert response.json()["user_id"] == ""
    assert response.json()["tenant_id"] == ""


@pytest.mark.asyncio
async def test_request_context_isolated_between_concurrent_requests() -> None:
    import asyncio

    import httpx
    from fastapi import FastAPI, Request

    from app.api.middleware.request_context import RequestContextMiddleware as RequestIDMiddleware
    from app.infrastructure.observability.logging import get_request_context
    from app.infrastructure.runtime.request_state import get_request_state

    app = FastAPI()
    app.add_middleware(RequestIDMiddleware)

    @app.get("/")
    async def read(request: Request) -> dict:
        await asyncio.sleep(0)
        get_request_state().cached_request_id = request.state.request_id
        assert request.state.cached_request_id == request.state.request_id
        return get_request_context()

    before = get_request_context()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        responses = await asyncio.gather(
            client.get("/", headers={"X-Request-ID": "first"}),
            client.get("/", headers={"X-Request-ID": "second"}),
        )

    assert [response.json()["request_id"] for response in responses] == ["first", "second"]
    assert [response.headers["X-Request-ID"] for response in responses] == ["first", "second"]
    assert get_request_context() == before


@pytest.mark.asyncio
async def test_request_context_restored_when_downstream_fails() -> None:
    from starlette.requests import Request

    from app.api.middleware.request_context import RequestContextMiddleware as RequestIDMiddleware
    from app.infrastructure.observability.logging import (
        bind_request_context,
        get_request_context,
        reset_request_context,
    )
    from app.infrastructure.runtime.request_state import bind_request_state, get_request_state, reset_request_state

    outer_state = object()
    state_token = bind_request_state(outer_state)
    context_tokens = bind_request_context(request_id="outer", tenant_id="workspace", user_id="local", route="outer")
    before = get_request_context()

    async def app(scope, receive, send) -> None:
        raise AssertionError("dispatch is exercised directly")

    async def fail(request: Request):
        assert get_request_state() is request.state
        assert get_request_context()["request_id"] == "inner"
        raise RuntimeError("route failed")

    request = Request({"type": "http", "path": "/fail", "headers": [(b"x-request-id", b"inner")]})
    try:
        with pytest.raises(RuntimeError, match="route failed"):
            await RequestIDMiddleware(app).dispatch(request, fail)
        assert get_request_context() == before
        assert get_request_state() is outer_state
    finally:
        reset_request_context(context_tokens)
        reset_request_state(state_token)

from __future__ import annotations

import inspect

import httpx
import pytest

from app.core.logging_config import bind_request_context, reset_request_context
from tests.helpers.async_utils import yield_control


@pytest.mark.asyncio
async def test_request_with_retry_can_use_external_client(monkeypatch):
    import app.core.http_client as hc

    pool = hc.HTTPClientPool()

    sig = inspect.signature(pool.request_with_retry)
    assert "use_external_client" in sig.parameters

    request = httpx.Request("GET", "http://example.local")
    resp200 = httpx.Response(200, request=request, content=b"ok")

    class _DummyClient:
        async def request(self, _method: str, _url: str, **_kwargs):  # noqa: ANN001
            await yield_control()
            return resp200

    async def _get_external_client():  # noqa: ANN001
        await yield_control()
        return _DummyClient()

    async def _get_client():  # noqa: ANN001
        await yield_control()
        raise AssertionError("internal client should not be used when use_external_client=True")

    monkeypatch.setattr(pool, "get_external_client", _get_external_client)
    monkeypatch.setattr(pool, "get_client", _get_client)

    res = await pool.request_with_retry("GET", "http://example.local", max_retries=0, use_external_client=True)
    assert res.status_code == 200


@pytest.mark.asyncio
async def test_request_with_retry_async_clients_use_awaitable_context_hooks(monkeypatch):
    import app.core.http_client as hc

    pool = hc.HTTPClientPool()

    class _DummyAsyncClient:
        def __init__(self, **kwargs):  # noqa: ANN003
            self._event_hooks = kwargs.get("event_hooks", {})
            self.requests: list[httpx.Request] = []

        async def request(self, method: str, url: str, **_kwargs):  # noqa: ANN001
            await yield_control()
            req = httpx.Request(method, url)
            for hook in self._event_hooks.get("request", []):
                await hook(req)
            self.requests.append(req)
            return httpx.Response(200, request=req, content=b"ok")

        async def aclose(self):
            await yield_control()

    monkeypatch.setattr(hc.httpx, "AsyncClient", _DummyAsyncClient)
    monkeypatch.setattr(pool, "_build_trust_env", lambda: False)
    monkeypatch.setattr(pool, "_build_http2", lambda: False)

    tokens = bind_request_context(request_id="rid", tenant_id="tid", user_id="uid")
    try:
        internal = await pool.request_with_retry("GET", "http://example.local/internal", max_retries=0)
        external = await pool.request_with_retry(
            "GET",
            "http://example.local/external",
            max_retries=0,
            use_external_client=True,
        )
        internal_client = pool._async_client
        external_client = pool._async_client_external
    finally:
        reset_request_context(tokens)
        await pool.close()

    assert internal.status_code == 200
    assert external.status_code == 200

    assert internal_client is not None
    assert external_client is not None

    internal_request = internal_client.requests[0]
    external_request = external_client.requests[0]

    assert internal_request.headers.get("X-Request-ID") == "rid"
    assert internal_request.headers.get("X-Tenant-ID") == "tid"
    assert internal_request.headers.get("X-User-ID") == "uid"

    assert external_request.headers.get("X-Request-ID") == "rid"
    assert external_request.headers.get("X-Tenant-ID") is None
    assert external_request.headers.get("X-User-ID") is None

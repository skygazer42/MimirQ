from __future__ import annotations

import asyncio
import inspect

import httpx
import pytest


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
            await asyncio.sleep(0)  # Sonar S7503
            return resp200

    async def _get_external_client():  # noqa: ANN001
        await asyncio.sleep(0)  # Sonar S7503
        return _DummyClient()

    async def _get_client():  # noqa: ANN001
        await asyncio.sleep(0)  # Sonar S7503
        raise AssertionError("internal client should not be used when use_external_client=True")

    monkeypatch.setattr(pool, "get_external_client", _get_external_client)
    monkeypatch.setattr(pool, "get_client", _get_client)

    res = await pool.request_with_retry("GET", "http://example.local", max_retries=0, use_external_client=True)
    assert res.status_code == 200


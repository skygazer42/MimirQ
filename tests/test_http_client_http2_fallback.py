from __future__ import annotations

import asyncio

import pytest


class _DummyAsyncClient:
    def __init__(self, *, http2: bool, **_kwargs):
        self.http2 = http2

    async def aclose(self) -> None:
        await asyncio.sleep(0)  # Sonar S7503
        return None


@pytest.mark.asyncio
async def test_http2_disabled_when_h2_missing(monkeypatch):
    # Ensure no ImportError is raised if HTTP/2 deps aren't installed.
    import app.core.http_client as hc

    created = {}

    def _factory(*, http2: bool, **kwargs):
        created["http2"] = http2
        return _DummyAsyncClient(http2=http2, **kwargs)

    monkeypatch.setattr(hc, "_HTTP2_AVAILABLE", False)
    monkeypatch.setattr(hc.settings, "HTTP_CLIENT_HTTP2_ENABLED", True, raising=False)
    monkeypatch.setattr(hc.httpx, "AsyncClient", _factory)

    pool = hc.HTTPClientPool()
    await pool.get_client()

    assert created["http2"] is False


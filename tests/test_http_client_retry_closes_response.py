from __future__ import annotations

import asyncio

import httpx
import pytest


class _DummyAsyncClient:
    def __init__(self, responses: list[httpx.Response]) -> None:
        self._responses = list(responses)
        self._i = 0

    async def request(self, _method: str, _url: str, **_kwargs):  # noqa: ANN001
        await asyncio.sleep(0)  # Sonar S7503
        resp = self._responses[self._i]
        self._i += 1
        return resp


@pytest.mark.asyncio
async def test_request_with_retry_closes_error_response_before_retry(monkeypatch):
    import app.core.http_client as hc

    request = httpx.Request("GET", "http://example.local")
    resp500 = httpx.Response(500, request=request, content=b"err")
    resp200 = httpx.Response(200, request=request, content=b"ok")

    closed = {"called": False}
    orig_aclose = resp500.aclose

    async def _aclose():  # noqa: ANN001
        closed["called"] = True
        await orig_aclose()

    resp500.aclose = _aclose  # type: ignore[assignment]

    dummy = _DummyAsyncClient([resp500, resp200])

    pool = hc.HTTPClientPool()

    async def _get_client():  # noqa: ANN001
        await asyncio.sleep(0)  # Sonar S7503
        return dummy

    monkeypatch.setattr(pool, "get_client", _get_client)

    res = await pool.request_with_retry(
        "GET",
        "http://example.local",
        max_retries=1,
        retry_delay=0.0,
        backoff_factor=1.0,
        jitter=0.0,
    )

    assert res.status_code == 200
    assert closed["called"] is True


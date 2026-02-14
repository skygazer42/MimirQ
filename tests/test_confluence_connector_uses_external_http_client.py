from __future__ import annotations

import httpx
import pytest


@pytest.mark.asyncio
async def test_confluence_request_helper_forces_external_http_client():
    import app.api.v1.connectors as connectors

    fn = getattr(connectors, "_confluence_request", None)
    assert callable(fn)

    seen: dict[str, object] = {}

    class _FakePool:
        async def request_with_retry(self, method: str, url: str, **kwargs):  # noqa: ANN201
            seen["use_external_client"] = kwargs.get("use_external_client")
            return httpx.Response(200, request=httpx.Request(method, url))

    pool = _FakePool()
    res = await fn(pool, "GET", "https://example.com/api", headers={"Accept": "application/json"})
    assert res.status_code == 200
    assert seen.get("use_external_client") is True


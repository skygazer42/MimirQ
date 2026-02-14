from __future__ import annotations

import httpx

from app.core.http_client import HTTPClientPool
from app.core.logging_config import bind_request_context, reset_request_context


def test_http_client_pool_exposes_external_clients():
    pool = HTTPClientPool()
    assert hasattr(pool, "get_external_sync_client")
    assert hasattr(pool, "get_external_async_client")


def test_external_context_headers_do_not_include_tenant_or_user():
    pool = HTTPClientPool()
    hook = getattr(pool, "_inject_external_context_headers", None)
    assert callable(hook)

    tokens = bind_request_context(request_id="rid", tenant_id="tid", user_id="uid")
    try:
        req = httpx.Request("GET", "https://example.com/")
        hook(req)
        assert req.headers.get("X-Request-ID") == "rid"
        assert "X-Tenant-ID" not in req.headers
        assert "X-User-ID" not in req.headers
    finally:
        reset_request_context(tokens)


def test_internal_context_headers_include_tenant_and_user():
    pool = HTTPClientPool()
    hook = getattr(pool, "_inject_internal_context_headers", None)
    assert callable(hook)

    tokens = bind_request_context(request_id="rid", tenant_id="tid", user_id="uid")
    try:
        req = httpx.Request("GET", "https://example.com/")
        hook(req)
        assert req.headers.get("X-Request-ID") == "rid"
        assert req.headers.get("X-Tenant-ID") == "tid"
        assert req.headers.get("X-User-ID") == "uid"
    finally:
        reset_request_context(tokens)


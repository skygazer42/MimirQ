from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient


def _build_app() -> FastAPI:
    from app.core.exceptions import register_exception_handlers

    app = FastAPI()
    register_exception_handlers(app)
    return app


def test_http_exception_handler_preserves_retry_after_header() -> None:
    app = _build_app()

    @app.get("/limited")
    def limited():  # noqa: ANN201
        raise HTTPException(
            status_code=429,
            detail={
                "message": "Too many requests",
                "retry_after_sec": 3,
                "limit": 10,
                "scope": "test",
            },
            headers={"Retry-After": "3"},
        )

    client = TestClient(app)
    res = client.get("/limited")

    assert res.status_code == 429
    assert res.headers.get("Retry-After") == "3"

    payload = res.json()
    assert payload.get("error") == "RATE_LIMIT_EXCEEDED"
    assert payload.get("message") == "Too many requests"
    assert (payload.get("detail") or {}).get("retry_after_sec") == 3
    assert (payload.get("detail") or {}).get("limit") == 10
    assert (payload.get("detail") or {}).get("scope") == "test"


def test_rate_limit_middleware_returns_standard_429_body_and_header() -> None:
    from app.api.middleware.rate_limit import RateLimitMiddleware

    app = _build_app()
    app.add_middleware(RateLimitMiddleware, requests_per_second=1, burst_size=1)

    @app.get("/ping")
    def ping():  # noqa: ANN201
        return {"ok": True}

    client = TestClient(app)

    first = client.get("/ping")
    assert first.status_code == 200

    second = client.get("/ping")
    assert second.status_code == 429

    payload = second.json()
    detail = payload.get("detail") or {}

    assert payload.get("error") == "RATE_LIMIT_EXCEEDED"
    assert payload.get("message") == "Too many requests. Please try again later."
    assert detail.get("scope") == "rate_limit:api"
    assert detail.get("limit") == pytest.approx(1.0)
    assert isinstance(detail.get("retry_after_sec"), int)
    assert second.headers.get("Retry-After") == str(detail.get("retry_after_sec"))


def test_rate_limit_middleware_does_not_count_cors_preflight_options() -> None:
    from app.api.middleware.rate_limit import RateLimitMiddleware

    app = _build_app()
    app.add_middleware(RateLimitMiddleware, requests_per_second=1, burst_size=1)

    @app.options("/ping")
    def ping_preflight():  # noqa: ANN201
        return {"ok": True}

    @app.get("/ping")
    def ping():  # noqa: ANN201
        return {"ok": True}

    client = TestClient(app)

    preflight = client.options("/ping")
    assert preflight.status_code == 200

    first_get = client.get("/ping")
    assert first_get.status_code == 200

    second_get = client.get("/ping")
    assert second_get.status_code == 429


def test_tenant_qps_quota_429_has_standard_shape_and_retry_after_header(monkeypatch) -> None:
    import app.services.tenant_quota_service as quota_mod
    from app.core.config import settings

    # Ensure the module picks up our config changes.
    quota_mod._tenant_qps_limiter = None
    quota_mod._tenant_qps_cfg = None

    monkeypatch.setattr(settings, "RATE_LIMIT_REDIS_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "REDIS_URL", "", raising=False)
    monkeypatch.setattr(settings, "TENANT_QPS_QUOTA_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "TENANT_QPS_QUOTA_REQUESTS_PER_SECOND", 1.0, raising=False)
    monkeypatch.setattr(settings, "TENANT_QPS_QUOTA_BURST_SIZE", 1, raising=False)
    monkeypatch.setattr(settings, "TENANT_QPS_QUOTA_MODE", "block", raising=False)

    app = _build_app()
    tenant_id = uuid.uuid4()

    @app.get("/quota")
    def quota():  # noqa: ANN201
        quota_mod.enforce_tenant_qps_quota(tenant_id=tenant_id, key="retrieval")
        return {"ok": True}

    client = TestClient(app)

    first = client.get("/quota")
    assert first.status_code == 200

    second = client.get("/quota")
    assert second.status_code == 429

    payload = second.json()
    detail = payload.get("detail") or {}

    assert payload.get("error") == "RATE_LIMIT_EXCEEDED"
    assert detail.get("scope") == "tenant_qps:retrieval"
    assert detail.get("limit") == pytest.approx(1.0)
    assert isinstance(detail.get("retry_after_sec"), int)
    assert second.headers.get("Retry-After") == str(detail.get("retry_after_sec"))

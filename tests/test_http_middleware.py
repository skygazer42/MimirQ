import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from starlette.middleware.cors import CORSMiddleware

from app.api.middleware import request_context as process_time
from app.api.middleware.body_size_limit import BodySizeLimitMiddleware
from app.api.middleware.rate_limit import RateLimitMiddleware
from app.api.middleware.request_context import RequestContextMiddleware as RequestIDMiddleware
from app.api.middleware.request_context import RequestTimingMiddleware as ProcessTimeMiddleware
from app.api.middleware.response_headers import (
    ResponseFingerprintSanitizerMiddleware as ResponseHeaderSanitizerMiddleware,
)
from app.api.middleware.response_headers import ResponseSecurityHeadersMiddleware as SecurityHeadersMiddleware
from app.infrastructure.config import settings


def _rate_limited_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(BodySizeLimitMiddleware, max_body_bytes=10)
    app.add_middleware(
        RateLimitMiddleware,
        requests_per_second=0.000001,
        burst_size=1,
        chat_requests_per_second=0.000001,
        chat_burst_size=1,
        chat_route_prefixes=["/api/v1/chat/stream"],
    )

    @app.get("/api/work")
    @app.get("/api/v1/chat/stream")
    @app.get("/health")
    @app.get("/api/v1/documents/image/{name}")
    async def read() -> dict:
        return {"ok": True}

    @app.post("/upload")
    async def upload(payload: dict) -> dict:
        return payload

    @app.options("/api/work", status_code=204)
    async def preflight() -> None:
        return None

    return app


def _add_security_headers(app: FastAPI, *, frame_options: str = "DENY") -> None:
    app.add_middleware(
        SecurityHeadersMiddleware,
        x_content_type_options="nosniff",
        x_frame_options=frame_options,
        referrer_policy="strict-origin-when-cross-origin",
        strict_transport_security="max-age=100",
        permissions_policy="",
        cross_origin_opener_policy="",
        cross_origin_resource_policy="",
    )


def test_identity_headers_cannot_create_fresh_rate_limit_buckets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "RATE_LIMIT_REDIS_ENABLED", False)
    monkeypatch.setattr(settings, "AUTH_MODE", "header")
    app = _rate_limited_app()

    with TestClient(app) as client:
        first = client.get("/api/work", headers={"X-User-ID": "one", "X-Tenant-ID": "one"})
        second = client.get("/api/work", headers={"X-User-ID": "two", "X-Tenant-ID": "two"})

    assert first.status_code == 200
    assert second.status_code == 429
    assert int(second.headers["Retry-After"]) >= 1


def test_chat_and_api_have_separate_budgets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "RATE_LIMIT_REDIS_ENABLED", False)
    with TestClient(_rate_limited_app()) as client:
        assert client.get("/api/work").status_code == 200
        assert client.get("/api/v1/chat/stream").status_code == 200
        blocked_chat = client.get("/api/v1/chat/stream")
        blocked_api = client.get("/api/work")

    assert blocked_chat.status_code == blocked_api.status_code == 429
    assert blocked_chat.json()["detail"]["scope"] == "rate_limit:chat"
    assert blocked_api.json()["detail"]["scope"] == "rate_limit:api"


@pytest.mark.asyncio
async def test_missing_client_address_uses_one_shared_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx

    monkeypatch.setattr(settings, "RATE_LIMIT_REDIS_ENABLED", False)
    transport = httpx.ASGITransport(app=_rate_limited_app(), client=None)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        first = await client.get("/api/work")
        second = await client.get("/api/work")

    assert first.status_code == 200
    assert second.status_code == 429


def test_health_and_images_do_not_consume_api_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "RATE_LIMIT_REDIS_ENABLED", False)
    with TestClient(_rate_limited_app()) as client:
        assert client.options("/api/work").status_code == 204
        for path in ("/health", "/api/v1/documents/image/one", "/api/v1/documents/image/two"):
            assert client.get(path).status_code == 200
        assert client.get("/api/work").status_code == 200
        assert client.get("/api/work").status_code == 429


@pytest.mark.parametrize("enabled", [False, True])
def test_process_time_preserves_route_timing(monkeypatch: pytest.MonkeyPatch, enabled: bool) -> None:
    clock_values = iter([1.0, 1.0125])
    monkeypatch.setattr(process_time, "perf_counter", clock_values.__next__)
    app = FastAPI()
    app.add_middleware(ProcessTimeMiddleware, server_timing_enabled=enabled)

    @app.get("/")
    async def read() -> JSONResponse:
        return JSONResponse({}, headers={"Server-Timing": "db;dur=4"})

    with TestClient(app) as client:
        response = client.get("/")

    assert response.headers["X-Process-Time-Ms"] == "12.5"
    expected = "db;dur=4, app;dur=12.5" if enabled else "db;dur=4"
    assert response.headers["Server-Timing"] == expected


@pytest.mark.parametrize("frame_options", ["DENY", ""])
def test_security_headers_preserve_route_policy_and_disabled_values(frame_options: str) -> None:
    app = FastAPI()
    _add_security_headers(app, frame_options=frame_options)

    @app.get("/")
    async def read() -> JSONResponse:
        return JSONResponse({}, headers={"Referrer-Policy": "no-referrer"})

    with TestClient(app) as client:
        response = client.get("/")

    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert response.headers["Strict-Transport-Security"] == "max-age=100"
    assert "Permissions-Policy" not in response.headers
    if frame_options:
        assert response.headers["X-Frame-Options"] == frame_options
    else:
        assert "X-Frame-Options" not in response.headers


def test_header_sanitizer_removes_all_fingerprint_headers_and_duplicates() -> None:
    app = FastAPI()
    app.add_middleware(ResponseHeaderSanitizerMiddleware)

    @app.get("/")
    async def read() -> JSONResponse:
        response = JSONResponse({}, headers={"X-Custom": "kept"})
        for header in ("Server", "X-Powered-By", "X-AspNet-Version", "X-AspNetMvc-Version"):
            response.headers.append(header, "secret")
        response.headers.append("Server", "another")
        return response

    with TestClient(app) as client:
        response = client.get("/")

    assert response.headers["X-Custom"] == "kept"
    assert all(
        name not in response.headers for name in ("Server", "X-Powered-By", "X-AspNet-Version", "X-AspNetMvc-Version")
    )


@pytest.mark.parametrize("error_status", [413, 429])
def test_combined_middleware_keeps_error_status_and_response_headers(
    monkeypatch: pytest.MonkeyPatch, error_status: int
) -> None:
    monkeypatch.setattr(settings, "RATE_LIMIT_REDIS_ENABLED", False)
    app = _rate_limited_app()
    app.add_middleware(ProcessTimeMiddleware, server_timing_enabled=True)
    _add_security_headers(app)
    app.add_middleware(ResponseHeaderSanitizerMiddleware)
    app.add_middleware(RequestIDMiddleware)
    app.add_middleware(CORSMiddleware, allow_origins=["https://client.example"])

    with TestClient(app) as client:
        if error_status == 413:
            response = client.post(
                "/upload",
                json={"message": "too large"},
                headers={"X-Request-ID": "body-error", "Origin": "https://client.example"},
            )
        else:
            assert client.get("/api/work").status_code == 200
            response = client.get(
                "/api/work", headers={"X-Request-ID": "rate-error", "Origin": "https://client.example"}
            )

    assert response.status_code == error_status
    assert response.headers["X-Request-ID"] == ("body-error" if error_status == 413 else "rate-error")
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert "X-Process-Time-Ms" in response.headers
    assert "Server-Timing" in response.headers
    assert response.headers["Access-Control-Allow-Origin"] == "https://client.example"

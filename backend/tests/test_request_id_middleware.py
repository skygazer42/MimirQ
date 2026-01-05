from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.api.middleware.request_id import RequestIDMiddleware


def _make_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(RequestIDMiddleware)

    @app.get("/ping")
    async def ping(request: Request) -> dict:
        return {"request_id": getattr(request.state, "request_id", None)}

    return app


def test_request_id_generated_and_propagated():
    client = TestClient(_make_app())
    res = client.get("/ping")
    assert res.status_code == 200
    assert res.headers.get("X-Request-ID")
    assert res.json()["request_id"] == res.headers["X-Request-ID"]


def test_request_id_echoes_valid_client_header():
    client = TestClient(_make_app())
    res = client.get("/ping", headers={"X-Request-ID": "req-123"})
    assert res.status_code == 200
    assert res.headers["X-Request-ID"] == "req-123"
    assert res.json()["request_id"] == "req-123"


def test_request_id_rejects_unsafe_header_values():
    client = TestClient(_make_app())
    res = client.get("/ping", headers={"X-Request-ID": "bad\nid"})
    assert res.status_code == 200
    assert res.headers["X-Request-ID"] != "bad\nid"
    assert res.json()["request_id"] == res.headers["X-Request-ID"]


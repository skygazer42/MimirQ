from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.middleware.process_time import ProcessTimeMiddleware


def test_server_timing_header_enabled() -> None:
    app = FastAPI()
    app.add_middleware(ProcessTimeMiddleware, server_timing_enabled=True, server_timing_metric="app")

    @app.get("/ping")
    def ping():  # noqa: ANN202
        return {"ok": True}

    client = TestClient(app)
    res = client.get("/ping")

    assert "X-Process-Time-Ms" in res.headers
    assert "Server-Timing" in res.headers
    assert "app;dur=" in res.headers["Server-Timing"]


def test_server_timing_header_disabled() -> None:
    app = FastAPI()
    app.add_middleware(ProcessTimeMiddleware, server_timing_enabled=False)

    @app.get("/ping")
    def ping():  # noqa: ANN202
        return {"ok": True}

    client = TestClient(app)
    res = client.get("/ping")

    assert "X-Process-Time-Ms" in res.headers
    assert "Server-Timing" not in res.headers


from __future__ import annotations

from fastapi import FastAPI, Response
from fastapi.testclient import TestClient

from app.api.middleware.process_time import ProcessTimeMiddleware


def test_process_time_headers_present() -> None:
    app = FastAPI()
    app.add_middleware(ProcessTimeMiddleware, server_timing_enabled=True)

    @app.get("/ping")
    def ping():
        return {"ok": True}

    client = TestClient(app)
    r = client.get("/ping")
    assert r.status_code == 200
    assert "X-Process-Time-Ms" in r.headers
    assert float(r.headers["X-Process-Time-Ms"]) >= 0.0
    assert "Server-Timing" in r.headers
    assert "app;dur=" in r.headers["Server-Timing"]


def test_process_time_appends_server_timing() -> None:
    app = FastAPI()
    app.add_middleware(ProcessTimeMiddleware, server_timing_enabled=True, server_timing_metric="app")

    @app.get("/timed")
    def timed():
        # Pre-existing server timing entry.
        resp = Response(content="ok", media_type="text/plain")
        resp.headers["Server-Timing"] = "db;dur=1.0"
        return resp

    client = TestClient(app)
    r = client.get("/timed")
    assert r.status_code == 200
    assert r.headers["Server-Timing"].startswith("db;dur=1.0")
    assert "app;dur=" in r.headers["Server-Timing"]


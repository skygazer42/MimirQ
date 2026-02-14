from __future__ import annotations

import importlib

from fastapi import FastAPI, Response
from fastapi.testclient import TestClient


def test_response_header_sanitizer_middleware_removes_fingerprint_headers():
    mod = None
    try:
        mod = importlib.import_module("app.api.middleware.response_header_sanitizer")
    except ModuleNotFoundError:
        mod = None

    assert mod is not None
    mw_cls = getattr(mod, "ResponseHeaderSanitizerMiddleware", None)
    assert mw_cls is not None

    app = FastAPI()
    app.add_middleware(
        mw_cls,
        strip_headers=["Server", "X-Powered-By"],
    )

    @app.get("/ping")
    def ping():  # noqa: ANN201
        resp = Response(content="ok")
        resp.headers["Server"] = "uvicorn"
        resp.headers["X-Powered-By"] = "FastAPI"
        resp.headers["X-Content-Type-Options"] = "nosniff"
        return resp

    client = TestClient(app)
    res = client.get("/ping")
    assert res.status_code == 200
    assert "Server" not in res.headers
    assert "X-Powered-By" not in res.headers
    # Unrelated headers are preserved.
    assert res.headers.get("X-Content-Type-Options") == "nosniff"


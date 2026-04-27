from __future__ import annotations

import importlib

from fastapi import FastAPI
from fastapi.testclient import TestClient


def test_body_size_limit_middleware_blocks_large_requests():
    mod = None
    try:
        mod = importlib.import_module("app.api.middleware.body_size_limit")
    except ModuleNotFoundError:
        mod = None
    assert mod is not None
    mw_cls = getattr(mod, "BodySizeLimitMiddleware", None)
    assert mw_cls is not None

    app = FastAPI()
    app.add_middleware(mw_cls, max_body_bytes=10)

    @app.post("/echo")
    def echo():  # noqa: ANN201
        return {"ok": True}

    client = TestClient(app)

    small = client.post("/echo", content="x" * 5)
    assert small.status_code == 200

    big = client.post("/echo", content="x" * 20)
    assert big.status_code == 413

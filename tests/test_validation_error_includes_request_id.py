from __future__ import annotations

from fastapi import FastAPI, Query
from fastapi.testclient import TestClient

from app.api.middleware.request_id import RequestIDMiddleware
from app.core.exceptions import register_exception_handlers


def _make_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(RequestIDMiddleware)
    register_exception_handlers(app)

    @app.get("/items")
    async def list_items(limit: int = Query(default=10, ge=1, le=100)) -> dict:
        return {"limit": limit}

    return app


def test_request_validation_error_has_request_id_and_errors():
    client = TestClient(_make_app())
    res = client.get("/items", params={"limit": "nope"})

    assert res.status_code == 422
    assert res.headers.get("X-Request-ID")

    payload = res.json()
    assert payload.get("error") == "VALIDATION_ERROR"
    assert payload.get("request_id") == res.headers["X-Request-ID"]
    assert isinstance(payload.get("detail", {}).get("errors"), list)


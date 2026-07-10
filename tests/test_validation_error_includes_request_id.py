
import httpx
import pytest
from fastapi import FastAPI, Query

from app.api.middleware.request_id import RequestIDMiddleware
from app.core.exceptions import register_exception_handlers
from tests.helpers.async_utils import yield_control


def _make_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(RequestIDMiddleware)
    register_exception_handlers(app)

    @app.get("/items")
    async def list_items(limit: int = Query(default=10, ge=1, le=100)) -> dict:
        await yield_control()
        return {"limit": limit}

    return app


@pytest.mark.asyncio
async def test_request_validation_error_has_request_id_and_errors():
    transport = httpx.ASGITransport(app=_make_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/items", params={"limit": "nope"})

    assert res.status_code == 422
    assert res.headers.get("X-Request-ID")

    payload = res.json()
    assert payload.get("error") == "VALIDATION_ERROR"
    assert payload.get("request_id") == res.headers["X-Request-ID"]
    assert isinstance(payload.get("detail", {}).get("errors"), list)

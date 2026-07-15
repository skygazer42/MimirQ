
import httpx
import pytest
from fastapi import FastAPI, HTTPException, Query

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

    @app.get("/errors/{status_code}")
    async def raise_http_error(status_code: int) -> None:
        raise HTTPException(status_code=status_code, detail="expected failure")

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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "error_code"),
    [(400, "BAD_REQUEST"), (409, "CONFLICT"), (416, "RANGE_NOT_SATISFIABLE")],
)
async def test_http_exception_uses_stable_error_code(status_code: int, error_code: str):
    transport = httpx.ASGITransport(app=_make_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get(f"/errors/{status_code}")

    assert res.status_code == status_code
    assert res.json()["error"] == error_code

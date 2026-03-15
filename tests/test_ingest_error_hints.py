from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI, HTTPException

from app.api.middleware.request_id import RequestIDMiddleware
from app.core.exceptions import register_exception_handlers
from tests.helpers.async_utils import yield_control


def _make_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(RequestIDMiddleware)
    register_exception_handlers(app)

    @app.get("/parse-timeout")
    async def parse_timeout() -> None:
        await yield_control()
        raise HTTPException(
            status_code=500,
            detail={"message": "Failed to parse document", "hint_key": "timeout"},
        )

    @app.get("/too-large")
    async def too_large() -> None:
        await yield_control()
        raise HTTPException(status_code=413, detail="File too large")

    return app


@pytest.mark.asyncio
async def test_http_exception_hint_key_is_exposed() -> None:
    transport = httpx.ASGITransport(app=_make_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/parse-timeout")

    assert res.status_code == 500
    payload = res.json()
    assert payload.get("error")
    assert payload.get("message") == "Failed to parse document"
    assert isinstance(payload.get("hint"), str) and payload["hint"].strip()


@pytest.mark.asyncio
async def test_payload_too_large_has_hint() -> None:
    transport = httpx.ASGITransport(app=_make_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/too-large")

    assert res.status_code == 413
    payload = res.json()
    assert payload.get("message")
    assert isinstance(payload.get("hint"), str) and payload["hint"].strip()


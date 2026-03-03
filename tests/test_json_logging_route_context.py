from __future__ import annotations

import json
import logging
import uuid

import pytest
from fastapi import APIRouter, Depends, FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies.logging import bind_route_context
from app.api.middleware.request_id import RequestIDMiddleware
from app.core.logging_config import (
    JSONFormatter,
    bind_request_context,
    configure_logging,
    reset_request_context,
    set_request_route,
)


def test_json_formatter_includes_route_from_contextvars() -> None:
    tokens = bind_request_context(request_id="rid", tenant_id="tid", user_id="uid", route="/raw")
    try:
        set_request_route("/api/v1/items/{item_id}")

        record = logging.LogRecord(
            name="test.logger",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="hello",
            args=(),
            exc_info=None,
        )
        payload = json.loads(JSONFormatter().format(record))

        assert payload["request_id"] == "rid"
        assert payload["tenant_id"] == "tid"
        assert payload["user_id"] == "uid"
        assert payload["route"] == "/api/v1/items/{item_id}"
    finally:
        reset_request_context(tokens)


def test_route_dependency_binds_route_template_for_request_logs(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    from app.core.config import settings

    # Allow RequestIDMiddleware to bind a trusted user id from header for this test.
    monkeypatch.setattr(settings, "AUTH_MODE", "header", raising=False)

    # Ensure the LogRecord factory attaches contextvars to records.
    configure_logging(log_level="INFO", log_format="plain", include_trace_context=False)

    app = FastAPI()
    app.add_middleware(RequestIDMiddleware)

    router = APIRouter(prefix="/api/v1", dependencies=[Depends(bind_route_context)])
    logger = logging.getLogger("test.route_context")

    @router.get("/items/{item_id}")
    def get_item(item_id: str):  # noqa: ANN001
        logger.info("handler log item_id=%s", item_id)
        return {"ok": True}

    app.include_router(router)

    tenant_id = str(uuid.uuid4())
    client = TestClient(app)
    with caplog.at_level(logging.INFO):
        res = client.get(
            "/api/v1/items/123",
            headers={
                "X-Request-ID": "rid-123",
                "X-Tenant-ID": tenant_id,
                "X-User-ID": "user-1",
            },
        )

    assert res.status_code == 200, res.text

    record = next(
        r for r in caplog.records if r.name == "test.route_context" and "handler log" in (r.getMessage() or "")
    )
    assert getattr(record, "request_id", "") == "rid-123"
    assert getattr(record, "tenant_id", "") == tenant_id
    assert getattr(record, "user_id", "") == "user-1"
    assert getattr(record, "route", "") == "/api/v1/items/{item_id}"


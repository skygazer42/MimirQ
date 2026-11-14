"""Request context and timing middleware."""

import re
import uuid
from time import perf_counter

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from app.core.logging_config import bind_request_context, reset_request_context
from app.core.request_state import bind_request_state, reset_request_state

_SAFE_REQUEST_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_\-:.]{0,127}")


def _normalize_request_id(raw: str | None) -> str:
    if raw is not None:
        request_id = raw.strip()
        if _SAFE_REQUEST_ID_RE.fullmatch(request_id):
            return request_id
    return uuid.uuid4().hex


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Bind request identity context and restore it after downstream processing."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = _normalize_request_id(request.headers.get("X-Request-ID"))
        request.state.request_id = request_id
        state_token = bind_request_state(request.state)
        context_tokens = bind_request_context(request_id=request_id, route=request.url.path)
        try:
            response = await call_next(request)
        finally:
            reset_request_state(state_token)
            reset_request_context(context_tokens)

        response.headers["X-Request-ID"] = request_id
        return response


class RequestTimingMiddleware(BaseHTTPMiddleware):
    """Add request duration headers while preserving existing timing entries."""

    def __init__(self, app: ASGIApp, *, server_timing_enabled: bool) -> None:
        super().__init__(app)
        self.server_timing_enabled = server_timing_enabled

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        started_at = perf_counter()
        response = await call_next(request)
        elapsed_ms = (perf_counter() - started_at) * 1000
        response.headers["X-Process-Time-Ms"] = f"{elapsed_ms:.1f}"
        if self.server_timing_enabled:
            timing_entry = f"app;dur={elapsed_ms:.1f}"
            existing_timing = response.headers.get("Server-Timing")
            response.headers["Server-Timing"] = (
                f"{existing_timing}, {timing_entry}" if existing_timing else timing_entry
            )
        return response


__all__ = ["RequestContextMiddleware", "RequestTimingMiddleware", "_normalize_request_id"]

"""
Request ID middleware.

Adds a stable request id to:
- request.state.request_id
- response header (default: X-Request-ID)
"""

import re
import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from app.core.config import settings
from app.core.logging_config import bind_request_context, reset_request_context
from app.core.request_state import bind_request_state, reset_request_state

_SAFE_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\-:.]{0,127}$")


def _normalize_request_id(raw: str | None) -> str:
    value = raw.strip() if raw is not None else None
    if not value:
        return uuid.uuid4().hex
    # Guard against header injection / unbounded values.
    if "\n" in value or "\r" in value or not _SAFE_REQUEST_ID_RE.match(value):
        return uuid.uuid4().hex
    return value


class RequestIDMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, *, header_name: str = "X-Request-ID") -> None:
        super().__init__(app)
        self.header_name = header_name

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = _normalize_request_id(request.headers.get(self.header_name))
        request.state.request_id = request_id
        state_token = bind_request_state(request.state)

        tenant_header = settings.TENANT_HEADER.strip() or "X-Tenant-ID"
        tenant_id = request.headers.get(tenant_header)
        if tenant_id is not None:
            tenant_id = tenant_id.strip()
        if not tenant_id and tenant_header.lower() != "x-tenant-id":
            tenant_id = request.headers.get("X-Tenant-ID")

        # Security: when AUTH_MODE=jwt, do not trust X-User-ID (spoofable) for logging context.
        context = {"request_id": request_id, "route": request.url.path}
        if tenant_id is not None:
            context["tenant_id"] = tenant_id.strip()
        if settings.AUTH_MODE == "header":
            user_id = request.headers.get("X-User-ID")
            if user_id is not None:
                context["user_id"] = user_id.strip()
        tokens = bind_request_context(**context)
        try:
            response = await call_next(request)
        finally:
            reset_request_state(state_token)
            reset_request_context(tokens)

        response.headers[self.header_name] = request_id
        return response

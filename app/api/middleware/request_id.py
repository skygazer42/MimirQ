"""
Request ID middleware.

Adds a stable request id to:
- request.state.request_id
- response header (default: X-Request-ID)
"""


import re
import uuid
from typing import Callable, Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.logging_config import bind_request_context, reset_request_context

_SAFE_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\-:.]{0,127}$")


def _normalize_request_id(raw: Optional[str]) -> str:
    value = (raw or "").strip()
    if not value:
        return uuid.uuid4().hex
    # Guard against header injection / unbounded values.
    if "\n" in value or "\r" in value or not _SAFE_REQUEST_ID_RE.match(value):
        return uuid.uuid4().hex
    return value


class RequestIDMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, *, header_name: str = "X-Request-ID") -> None:
        super().__init__(app)
        self.header_name = header_name

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        request_id = _normalize_request_id(request.headers.get(self.header_name))
        request.state.request_id = request_id

        tenant_id = (request.headers.get("X-Tenant-ID") or "").strip()
        user_id = (request.headers.get("X-User-ID") or "").strip()
        tokens = bind_request_context(request_id=request_id, tenant_id=tenant_id, user_id=user_id)
        try:
            response = await call_next(request)
        finally:
            reset_request_context(tokens)

        response.headers[self.header_name] = request_id
        return response

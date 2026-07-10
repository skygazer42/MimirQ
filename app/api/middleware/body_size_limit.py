"""
Request body size limit middleware.

This is a lightweight DoS guardrail:
- If Content-Length is present and exceeds the configured limit, reject early.
- If Content-Length is missing/invalid (e.g., chunked transfer), do not block here.

It is intentionally simple and fail-open for unknown body sizes.
"""


from collections.abc import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.status import HTTP_413_REQUEST_ENTITY_TOO_LARGE


class BodySizeLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, *, max_body_bytes: int = 0) -> None:
        super().__init__(app)
        self.max_body_bytes = max(0, int(max_body_bytes or 0))

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        limit = self.max_body_bytes
        if limit <= 0:
            return await call_next(request)

        raw = (request.headers.get("content-length") or "").strip()
        if raw:
            try:
                size = int(raw)
            except ValueError:
                size = -1
            if size > limit:
                return JSONResponse(
                    status_code=HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    content={"detail": "Request body too large"},
                )

        return await call_next(request)


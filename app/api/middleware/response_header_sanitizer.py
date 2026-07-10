"""
Response header sanitizer middleware.

Removes common response headers that can leak implementation details.

Note: Some headers (e.g. `Server`) may be added by the ASGI server/proxy layer
after the app has produced the response. This middleware is still useful for
headers produced by the application stack.
"""


from collections.abc import Callable, Iterable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

_DEFAULT_STRIP_HEADERS: tuple[str, ...] = (
    "Server",
    "X-Powered-By",
    "X-AspNet-Version",
    "X-AspNetMvc-Version",
)


class ResponseHeaderSanitizerMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, *, strip_headers: Iterable[str] | None = None) -> None:
        super().__init__(app)
        raw = list(strip_headers) if strip_headers is not None else list(_DEFAULT_STRIP_HEADERS)
        cleaned: list[str] = []
        seen: set[str] = set()
        for item in raw:
            name = str(item or "").strip()
            if not name:
                continue
            key = name.lower()
            if key in seen:
                continue
            seen.add(key)
            cleaned.append(name)
        self.strip_headers = tuple(cleaned)

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response = await call_next(request)
        for name in self.strip_headers:
            if name in response.headers:
                del response.headers[name]
        return response


"""
Process time middleware.

Adds a lightweight timing header to responses for debugging/perf checks:
- X-Process-Time-Ms
"""

from __future__ import annotations

from time import perf_counter
from typing import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class ProcessTimeMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, *, header_name: str = "X-Process-Time-Ms") -> None:
        super().__init__(app)
        self.header_name = header_name

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        start = perf_counter()
        response = await call_next(request)
        elapsed_ms = (perf_counter() - start) * 1000.0
        response.headers[self.header_name] = f"{elapsed_ms:.1f}"
        return response


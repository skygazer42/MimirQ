"""
Process time middleware.

Adds a lightweight timing header to responses for debugging/perf checks:
- X-Process-Time-Ms
- Server-Timing (optional)
"""


from collections.abc import Callable
from time import perf_counter

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class ProcessTimeMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app,
        *,
        header_name: str = "X-Process-Time-Ms",
        server_timing_enabled: bool = True,
        server_timing_header: str = "Server-Timing",
        server_timing_metric: str = "app",
    ) -> None:
        super().__init__(app)
        self.header_name = header_name
        self.server_timing_enabled = bool(server_timing_enabled)
        self.server_timing_header = str(server_timing_header or "Server-Timing")
        self.server_timing_metric = str(server_timing_metric or "app")

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        start = perf_counter()
        response = await call_next(request)
        elapsed_ms = (perf_counter() - start) * 1000.0
        response.headers[self.header_name] = f"{elapsed_ms:.1f}"
        if self.server_timing_enabled:
            metric = self.server_timing_metric
            if metric:
                entry = f"{metric};dur={elapsed_ms:.1f}"
                existing = response.headers.get(self.server_timing_header)
                response.headers[self.server_timing_header] = f"{existing}, {entry}" if existing else entry
        return response

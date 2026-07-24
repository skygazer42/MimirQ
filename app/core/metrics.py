"""
Prometheus metrics primitives.

Designed to be optional: metrics are enabled only when PROMETHEUS_ENABLED=true.
"""


import time
from collections.abc import Iterable

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest

HTTP_REQUESTS_TOTAL = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "path", "status"],
)
HTTP_REQUEST_DURATION_SECONDS = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration in seconds",
    ["method", "path"],
)
HTTP_REQUESTS_IN_PROGRESS = Gauge(
    "http_requests_in_progress",
    "In-progress HTTP requests",
    ["method", "path"],
)


def render_metrics() -> tuple[bytes, str]:
    return generate_latest(), CONTENT_TYPE_LATEST


_IN_PROGRESS_PATH_LABEL = "__all__"
_UNMATCHED_PATH_LABEL = "__unmatched__"


def _completed_path_label_from_scope(scope) -> str:  # type: ignore[no-untyped-def]
    route = scope.get("route")
    path_template = getattr(route, "path", None)
    if path_template:
        return str(path_template)
    return _UNMATCHED_PATH_LABEL


class PrometheusMiddleware:
    """
    ASGI middleware that collects per-request count/latency metrics.

    Labels:
    - method: HTTP method
    - path: route template for completed requests; bounded sentinels otherwise
    - status: HTTP response status code
    """

    def __init__(self, app, *, exclude_paths: Iterable[str] | None = None) -> None:
        self.app = app
        self.exclude_paths = set(exclude_paths or [])

    async def __call__(self, scope, receive, send) -> None:  # type: ignore[no-untyped-def]
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        raw_path = str(scope.get("path") or "")
        if raw_path in self.exclude_paths:
            await self.app(scope, receive, send)
            return

        method = str(scope.get("method") or "").upper()
        start = time.monotonic()
        status_code = 500

        HTTP_REQUESTS_IN_PROGRESS.labels(method=method, path=_IN_PROGRESS_PATH_LABEL).inc()

        async def send_wrapper(message):  # type: ignore[no-untyped-def]
            nonlocal status_code
            if message.get("type") == "http.response.start":
                status_code = int(message.get("status") or 500)
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            duration = max(0.0, time.monotonic() - start)
            path_label = _completed_path_label_from_scope(scope)
            HTTP_REQUESTS_TOTAL.labels(method=method, path=path_label, status=str(status_code)).inc()
            HTTP_REQUEST_DURATION_SECONDS.labels(method=method, path=path_label).observe(duration)
            HTTP_REQUESTS_IN_PROGRESS.labels(method=method, path=_IN_PROGRESS_PATH_LABEL).dec()

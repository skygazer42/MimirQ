from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.metrics import (
    HTTP_REQUEST_DURATION_SECONDS,
    HTTP_REQUESTS_IN_PROGRESS,
    HTTP_REQUESTS_TOTAL,
    PrometheusMiddleware,
)


def _clear_http_metrics() -> None:
    HTTP_REQUESTS_IN_PROGRESS._metrics.clear()  # type: ignore[attr-defined]
    HTTP_REQUESTS_TOTAL._metrics.clear()  # type: ignore[attr-defined]
    HTTP_REQUEST_DURATION_SECONDS._metrics.clear()  # type: ignore[attr-defined]


def test_prometheus_middleware_uses_single_bounded_in_progress_gauge_label() -> None:
    _clear_http_metrics()
    try:
        app = FastAPI()
        app.add_middleware(PrometheusMiddleware)

        @app.get("/items/{item_id}")
        def read_item(item_id: str) -> dict[str, float | str | None]:
            all_value = HTTP_REQUESTS_IN_PROGRESS.labels(method="GET", path="__all__")._value.get()
            raw_path = f"/items/{item_id}"
            raw_metric = HTTP_REQUESTS_IN_PROGRESS._metrics.get(("GET", raw_path))  # type: ignore[attr-defined]
            raw_value = raw_metric._value.get() if raw_metric is not None else None
            return {
                "all_value": all_value,
                "raw_value": raw_value,
            }

        client = TestClient(app)

        first = client.get(f"/items/{uuid4()}")
        second = client.get(f"/items/{uuid4()}")

        assert first.status_code == 200
        assert first.json() == {"all_value": 1.0, "raw_value": None}
        assert second.status_code == 200
        assert second.json() == {"all_value": 1.0, "raw_value": None}
        assert list(HTTP_REQUESTS_IN_PROGRESS._metrics) == [("GET", "__all__")]  # type: ignore[attr-defined]
    finally:
        _clear_http_metrics()


def test_prometheus_middleware_collapses_unmatched_paths() -> None:
    _clear_http_metrics()
    try:
        app = FastAPI()
        app.add_middleware(PrometheusMiddleware)
        client = TestClient(app)

        first = client.get(f"/missing/{uuid4()}")
        second = client.get(f"/unknown/{uuid4()}")

        assert first.status_code == 404
        assert second.status_code == 404
        assert list(HTTP_REQUESTS_TOTAL._metrics) == [("GET", "__unmatched__", "404")]  # type: ignore[attr-defined]
        assert list(HTTP_REQUEST_DURATION_SECONDS._metrics) == [("GET", "__unmatched__")]  # type: ignore[attr-defined]
    finally:
        _clear_http_metrics()

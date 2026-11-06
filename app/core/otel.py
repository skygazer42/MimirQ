"""
Optional OpenTelemetry tracing initialization.

Enabled when OTEL_ENABLED=true.
"""

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from fastapi import FastAPI

from app.core.config import settings

logger = logging.getLogger("mimirq.otel")

_initialized = False
_fastapi_instrumented = False


def init_otel() -> bool:
    """
    Initialize OpenTelemetry tracer provider and OTLP exporter.

    Notes:
    - Best-effort and safe to call multiple times.
    - When dependencies are missing, it logs a warning and returns False.
    """
    global _initialized
    if _initialized:
        return True

    if not settings.OTEL_ENABLED:
        return False

    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    service_name = (settings.OTEL_SERVICE_NAME or "mimirq").strip() or "mimirq"
    endpoint = (settings.OTEL_EXPORTER_OTLP_ENDPOINT or "").strip()
    headers = (settings.OTEL_EXPORTER_OTLP_HEADERS or "").strip()
    timeout_sec = float(settings.OTEL_EXPORTER_OTLP_TIMEOUT_SEC or 10)

    exporter_kwargs: dict[str, Any] = {}
    if endpoint:
        exporter_kwargs["endpoint"] = endpoint
    if headers:
        exporter_kwargs["headers"] = headers
    if timeout_sec > 0:
        exporter_kwargs["timeout"] = timeout_sec

    exporter = OTLPSpanExporter(**exporter_kwargs)
    provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)

    _initialized = True
    logger.info("OpenTelemetry tracing initialized (service=%s)", service_name)
    return True


def instrument_httpx() -> None:
    if not _initialized:
        return

    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

    try:
        HTTPXClientInstrumentor().instrument()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to instrument httpx for OpenTelemetry: %s", str(exc)[:200])


def instrument_fastapi(app: "FastAPI") -> None:
    global _fastapi_instrumented
    if not _initialized or _fastapi_instrumented:
        return

    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

    try:
        FastAPIInstrumentor.instrument_app(app)
        _fastapi_instrumented = True
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to instrument FastAPI for OpenTelemetry: %s", str(exc)[:200])


def shutdown_otel() -> None:
    if not _initialized:
        return

    try:
        from opentelemetry import trace

        provider = trace.get_tracer_provider()
        shutdown = getattr(provider, "shutdown", None)
        if callable(shutdown):
            shutdown()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to shutdown OpenTelemetry: %s", str(exc)[:200])

"""
Optional OpenTelemetry tracing initialization.

Enabled when OTEL_ENABLED=true.
"""


import logging

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

    if not bool(getattr(settings, "OTEL_ENABLED", False)):
        return False

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError as exc:
        logger.warning(
            "OpenTelemetry enabled but core deps are missing: %s (hint: pip install opentelemetry-sdk opentelemetry-exporter-otlp-proto-grpc)",
            str(exc)[:200],
        )
        return False

    service_name = str(getattr(settings, "OTEL_SERVICE_NAME", "mimirq") or "mimirq").strip() or "mimirq"
    endpoint = str(getattr(settings, "OTEL_EXPORTER_OTLP_ENDPOINT", "") or "").strip()
    headers = str(getattr(settings, "OTEL_EXPORTER_OTLP_HEADERS", "") or "").strip()
    timeout_sec = float(getattr(settings, "OTEL_EXPORTER_OTLP_TIMEOUT_SEC", 10) or 10)

    exporter_kwargs: dict = {}
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

    try:
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
    except ImportError as exc:
        logger.warning(
            "OpenTelemetry httpx instrumentation missing: %s (hint: pip install opentelemetry-instrumentation-httpx)",
            str(exc)[:200],
        )
        return

    try:
        HTTPXClientInstrumentor().instrument()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to instrument httpx for OpenTelemetry: %s", str(exc)[:200])


def instrument_fastapi(app) -> None:  # type: ignore[no-untyped-def]
    global _fastapi_instrumented
    if not _initialized or _fastapi_instrumented:
        return

    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    except ImportError as exc:
        logger.warning(
            "OpenTelemetry FastAPI instrumentation missing: %s (hint: pip install opentelemetry-instrumentation-fastapi)",
            str(exc)[:200],
        )
        return

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

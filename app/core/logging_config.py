"""
Request-scoped structured logging helpers.

This module:
- Stores per-request context (request_id/tenant_id/user_id) via contextvars
- Optionally configures JSON logging when LOG_FORMAT=json
"""

import json
import logging
import sys
from contextvars import ContextVar, Token
from datetime import UTC, datetime
from typing import Any

_request_id: ContextVar[str] = ContextVar("request_id", default="")
_tenant_id: ContextVar[str] = ContextVar("tenant_id", default="")
_user_id: ContextVar[str] = ContextVar("user_id", default="")
_route: ContextVar[str] = ContextVar("route", default="")

_record_factory_installed = False
_include_trace_context = True


def _get_otel_trace_context() -> tuple[str, str]:
    """
    Return (trace_id, span_id) for the current OpenTelemetry span, when available.

    Both values are lowercase hex strings (trace_id: 32 chars, span_id: 16 chars).
    Returns ("", "") when OpenTelemetry is not installed or no valid span is active.
    """
    if not _include_trace_context:
        return "", ""

    try:
        from opentelemetry import trace  # type: ignore
    except Exception:  # noqa: BLE001
        return "", ""

    try:
        span_context = trace.get_current_span().get_span_context()
        if not span_context.is_valid:
            return "", ""
        return format(span_context.trace_id, "032x"), format(span_context.span_id, "016x")
    except Exception:  # noqa: BLE001
        return "", ""


def bind_request_context(
    *, request_id: str, tenant_id: str = "", user_id: str = "", route: str = ""
) -> dict[str, Token[str]]:
    return {
        "request_id": _request_id.set(request_id.strip()),
        "tenant_id": _tenant_id.set(tenant_id.strip()),
        "user_id": _user_id.set(user_id.strip()),
        "route": _route.set(route.strip()),
    }


def set_request_user_id(user_id: str) -> None:
    """
    Update the current request's user_id context.

    Useful when auth is resolved after middleware binds initial context.
    """
    _user_id.set(user_id.strip())


def set_request_tenant_id(tenant_id: str) -> None:
    """
    Update the current request's tenant_id context.

    Useful when tenant identity is derived from a verified source (e.g. JWT claim)
    rather than an untrusted header.
    """
    _tenant_id.set(tenant_id.strip())


def set_request_route(route: str) -> None:
    """
    Update the current request's route template context.

    Prefer route templates (e.g. `/api/v1/rag/retrieve`) over raw paths to keep
    cardinality low in log search tools.
    """
    _route.set(route.strip())


def reset_request_context(tokens: dict[str, Token[str]]) -> None:
    if not tokens:
        return
    try:
        _request_id.reset(tokens["request_id"])
        _tenant_id.reset(tokens["tenant_id"])
        _user_id.reset(tokens["user_id"])
        _route.reset(tokens["route"])
    except (KeyError, ValueError):
        # Best-effort: never fail request processing due to logging context cleanup.
        return


def get_request_context() -> dict[str, str]:
    return {
        "request_id": _request_id.get(),
        "tenant_id": _tenant_id.get(),
        "user_id": _user_id.get(),
        "route": _route.get(),
    }


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }

        request_id = getattr(record, "request_id", _request_id.get())
        tenant_id = getattr(record, "tenant_id", _tenant_id.get())
        user_id = getattr(record, "user_id", _user_id.get())
        if request_id:
            payload["request_id"] = request_id
        if tenant_id:
            payload["tenant_id"] = tenant_id
        if user_id:
            payload["user_id"] = user_id

        route = getattr(record, "route", _route.get())
        if route:
            payload["route"] = route

        trace_id = getattr(record, "trace_id", None)
        span_id = getattr(record, "span_id", None)
        if trace_id:
            payload["trace_id"] = trace_id
        if span_id:
            payload["span_id"] = span_id

        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        if record.stack_info:
            payload["stack_info"] = self.formatStack(record.stack_info)
        return json.dumps(payload, ensure_ascii=False)


def _install_record_factory() -> None:
    global _record_factory_installed
    if _record_factory_installed:
        return

    old_factory = logging.getLogRecordFactory()

    def record_factory(*args: Any, **kwargs: Any) -> logging.LogRecord:
        record = old_factory(*args, **kwargs)
        record.request_id = _request_id.get()
        record.tenant_id = _tenant_id.get()
        record.user_id = _user_id.get()
        record.route = _route.get()
        trace_id, span_id = _get_otel_trace_context()
        record.trace_id = trace_id
        record.span_id = span_id
        return record

    logging.setLogRecordFactory(record_factory)
    _record_factory_installed = True


def configure_logging(
    *,
    log_level: str = "INFO",
    log_format: str = "plain",
    include_trace_context: bool = True,
) -> None:
    """
    Configure process-wide logging.

    Notes:
    - We keep this best-effort and safe to call multiple times.
    - When LOG_FORMAT=json, we force a root reconfiguration to ensure JSON output
      even when uvicorn pre-configures logging.
    """
    global _include_trace_context
    _include_trace_context = include_trace_context

    _install_record_factory()

    level = logging.getLevelNamesMapping().get(log_level.upper(), logging.INFO)

    if log_format.lower() != "json":
        # Best-effort: ensure the process respects LOG_LEVEL even when we keep plain logging.
        # Do not forcibly override existing handlers (e.g., uvicorn / pytest log capture).
        root = logging.getLogger()
        if not root.handlers:
            logging.basicConfig(level=level)
        else:
            root.setLevel(level)
        return

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())
    logging.basicConfig(level=level, handlers=[handler], force=True)

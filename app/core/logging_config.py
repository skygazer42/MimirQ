"""
Request-scoped structured logging helpers.

This module:
- Stores per-request context (request_id/tenant_id/user_id) via contextvars
- Optionally configures JSON logging when LOG_FORMAT=json
"""


import json
import logging
import sys
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any, Dict

_request_id: ContextVar[str] = ContextVar("request_id", default="")
_tenant_id: ContextVar[str] = ContextVar("tenant_id", default="")
_user_id: ContextVar[str] = ContextVar("user_id", default="")

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
        span = trace.get_current_span()
        if span is None:
            return "", ""
        ctx = span.get_span_context()
        if not getattr(ctx, "is_valid", False):
            return "", ""
        return format(int(ctx.trace_id), "032x"), format(int(ctx.span_id), "016x")
    except Exception:  # noqa: BLE001
        return "", ""


def bind_request_context(*, request_id: str, tenant_id: str = "", user_id: str = "") -> Dict[str, Any]:
    tokens: Dict[str, Any] = {}
    tokens["request_id"] = _request_id.set((request_id or "").strip())
    tokens["tenant_id"] = _tenant_id.set((tenant_id or "").strip())
    tokens["user_id"] = _user_id.set((user_id or "").strip())
    return tokens


def set_request_user_id(user_id: str) -> None:
    """
    Update the current request's user_id context.

    Useful when auth is resolved after middleware binds initial context.
    """
    _user_id.set((user_id or "").strip())


def set_request_tenant_id(tenant_id: str) -> None:
    """
    Update the current request's tenant_id context.

    Useful when tenant identity is derived from a verified source (e.g. JWT claim)
    rather than an untrusted header.
    """
    _tenant_id.set((tenant_id or "").strip())


def reset_request_context(tokens: Dict[str, Any]) -> None:
    if not tokens:
        return
    try:
        _request_id.reset(tokens["request_id"])
        _tenant_id.reset(tokens["tenant_id"])
        _user_id.reset(tokens["user_id"])
    except (KeyError, ValueError):
        # Best-effort: never fail request processing due to logging context cleanup.
        return


def get_request_context() -> Dict[str, str]:
    return {
        "request_id": _request_id.get() or "",
        "tenant_id": _tenant_id.get() or "",
        "user_id": _user_id.get() or "",
    }


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: Dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }

        request_id = getattr(record, "request_id", None) or _request_id.get() or ""
        tenant_id = getattr(record, "tenant_id", None) or _tenant_id.get() or ""
        user_id = getattr(record, "user_id", None) or _user_id.get() or ""
        if request_id:
            payload["request_id"] = request_id
        if tenant_id:
            payload["tenant_id"] = tenant_id
        if user_id:
            payload["user_id"] = user_id

        trace_id = getattr(record, "trace_id", None) or ""
        span_id = getattr(record, "span_id", None) or ""
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

    def record_factory(*args, **kwargs):  # type: ignore[no-untyped-def]
        record = old_factory(*args, **kwargs)
        record.request_id = _request_id.get() or ""
        record.tenant_id = _tenant_id.get() or ""
        record.user_id = _user_id.get() or ""
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
    _include_trace_context = bool(include_trace_context)

    _install_record_factory()

    level = int(logging._nameToLevel.get(str(log_level).upper(), logging.INFO))

    if str(log_format).lower() != "json":
        # Best-effort: ensure the process respects LOG_LEVEL even when we keep plain logging.
        # Do not forcibly override existing handlers (e.g., uvicorn / pytest log capture).
        root = logging.getLogger()
        if not getattr(root, "handlers", None):
            logging.basicConfig(level=level)
        else:
            root.setLevel(level)
        return

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())
    logging.basicConfig(level=level, handlers=[handler], force=True)

"""
Request-scoped structured logging helpers.

This module:
- Stores per-request context (request_id/tenant_id/user_id) via contextvars
- Optionally configures JSON logging when LOG_FORMAT=json
"""

from __future__ import annotations

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


def bind_request_context(*, request_id: str, tenant_id: str = "", user_id: str = "") -> Dict[str, Any]:
    tokens: Dict[str, Any] = {}
    tokens["request_id"] = _request_id.set((request_id or "").strip())
    tokens["tenant_id"] = _tenant_id.set((tenant_id or "").strip())
    tokens["user_id"] = _user_id.set((user_id or "").strip())
    return tokens


def reset_request_context(tokens: Dict[str, Any]) -> None:
    if not tokens:
        return
    try:
        _request_id.reset(tokens["request_id"])
        _tenant_id.reset(tokens["tenant_id"])
        _user_id.reset(tokens["user_id"])
    except Exception:  # noqa: BLE001
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
        return record

    logging.setLogRecordFactory(record_factory)
    _record_factory_installed = True


def configure_logging(*, log_level: str = "INFO", log_format: str = "plain") -> None:
    """
    Configure process-wide logging.

    Notes:
    - We keep this best-effort and safe to call multiple times.
    - When LOG_FORMAT=json, we force a root reconfiguration to ensure JSON output
      even when uvicorn pre-configures logging.
    """
    _install_record_factory()

    level = logging.INFO
    try:
        level = int(logging._nameToLevel.get(str(log_level).upper(), logging.INFO))
    except Exception:  # noqa: BLE001
        level = logging.INFO

    if str(log_format).lower() != "json":
        return

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())
    logging.basicConfig(level=level, handlers=[handler], force=True)


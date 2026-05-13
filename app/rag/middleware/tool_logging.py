"""
Tool call logging middleware.

Provides a reference implementation of `@wrap_tool_call`:
- Measures tool execution latency
- Attaches safe metadata to the tool-call state
- Optionally emits JSONL metrics via `log_metrics` (guarded by settings)
"""


import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.core.config import settings
from app.core.pii_redaction import pii_redaction_enabled, redact_text
from app.rag.core.logging import get_logger
from app.rag.middleware.base import wrap_tool_call
from app.services.metrics_logger import log_metrics

logger = get_logger("rag.middleware.tool_logging")


def _truncate_text(value: Any, max_chars: int) -> str:
    text = str(value) if value is not None else ""
    if max_chars > 0 and len(text) > max_chars:
        return text[:max_chars] + "..."
    return text


@dataclass
class ToolCallLoggingMiddleware:
    """
    Wrapper-style middleware for tool calls.

    The wrapped function is expected to accept/return a tool-call state dict:
        {
          "tool_name": str,
          "arguments": dict,
          "result": Any | None,
          "error": str | None,
          "success": bool | None,
          "metadata": dict,
        }
    """

    metrics_enabled: bool = False
    max_preview_chars: int = 500
    include_preview: bool = False

    def __call__(self, func: Callable) -> Callable:
        metrics_enabled = bool(self.metrics_enabled)
        max_preview_chars = max(0, int(self.max_preview_chars or 0))
        include_preview = bool(self.include_preview)

        pii_on = bool(pii_redaction_enabled())

        if asyncio.iscoroutinefunction(func):

            async def async_wrapper(state: dict[str, Any], *args, **kwargs) -> dict[str, Any]:
                tool_name = str(state.get("tool_name") or "")
                arg_keys = sorted((state.get("arguments") or {}).keys())
                t0 = time.time()
                try:
                    out = await func(state, *args, **kwargs)
                    elapsed_ms = round((time.time() - t0) * 1000, 2)

                    meta = dict(out.get("metadata") or {})
                    result_preview = None
                    error_preview = None
                    if include_preview:
                        result_preview = _truncate_text(out.get("result"), max_preview_chars) if out.get("result") is not None else None
                        error_preview = _truncate_text(out.get("error"), max_preview_chars) if out.get("error") else None
                        if pii_on:
                            result_preview = redact_text(result_preview) if result_preview else None
                            error_preview = redact_text(error_preview) if error_preview else None
                    meta["tool_call"] = {
                        "tool_name": tool_name,
                        "elapsed_ms": elapsed_ms,
                        "arguments_keys": arg_keys,
                        "success": bool(out.get("success")) if out.get("success") is not None else None,
                        "error_preview": error_preview,
                        "result_type": type(out.get("result")).__name__ if "result" in out else None,
                        "result_preview": result_preview,
                    }
                    out["metadata"] = meta

                    if metrics_enabled:
                        log_metrics(
                            {
                                "event": "tool_call",
                                "tool": tool_name,
                                "elapsed_ms": elapsed_ms,
                                "success": meta["tool_call"].get("success"),
                                "arguments_keys": arg_keys,
                                "error": meta["tool_call"].get("error_preview"),
                            }
                        )

                    return out
                except Exception as exc:  # noqa: BLE001
                    elapsed_ms = round((time.time() - t0) * 1000, 2)
                    if metrics_enabled:
                        log_metrics(
                            {
                                "event": "tool_call_error",
                                "tool": tool_name,
                                "elapsed_ms": elapsed_ms,
                                "error": str(exc)[:200],
                            }
                        )
                    raise

            return async_wrapper

        def sync_wrapper(state: dict[str, Any], *args, **kwargs) -> dict[str, Any]:
            tool_name = str(state.get("tool_name") or "")
            arg_keys = sorted((state.get("arguments") or {}).keys())
            t0 = time.time()
            out = func(state, *args, **kwargs)
            elapsed_ms = round((time.time() - t0) * 1000, 2)

            meta = dict(out.get("metadata") or {})
            result_preview = None
            error_preview = None
            if include_preview:
                result_preview = _truncate_text(out.get("result"), max_preview_chars) if out.get("result") is not None else None
                error_preview = _truncate_text(out.get("error"), max_preview_chars) if out.get("error") else None
                if pii_on:
                    result_preview = redact_text(result_preview) if result_preview else None
                    error_preview = redact_text(error_preview) if error_preview else None
            meta["tool_call"] = {
                "tool_name": tool_name,
                "elapsed_ms": elapsed_ms,
                "arguments_keys": arg_keys,
                "success": bool(out.get("success")) if out.get("success") is not None else None,
                "error_preview": error_preview,
                "result_type": type(out.get("result")).__name__ if "result" in out else None,
                "result_preview": result_preview,
            }
            out["metadata"] = meta

            if metrics_enabled:
                log_metrics(
                    {
                        "event": "tool_call",
                        "tool": tool_name,
                        "elapsed_ms": elapsed_ms,
                        "success": meta["tool_call"].get("success"),
                        "arguments_keys": arg_keys,
                        "error": meta["tool_call"].get("error_preview"),
                    }
                )

            return out

        return sync_wrapper


@wrap_tool_call(priority=50, name="tool_call_logging")
def _tool_call_logging_wrapper(func: Callable) -> Callable:
    enabled = bool(getattr(settings, "TOOL_CALL_LOG_ENABLED", False))
    include_preview = bool(getattr(settings, "TOOL_CALL_LOG_INCLUDE_PREVIEW", False))
    max_chars = int(getattr(settings, "TOOL_CALL_LOG_MAX_PREVIEW_CHARS", 500) or 500)
    if not enabled:
        return func
    return ToolCallLoggingMiddleware(
        metrics_enabled=bool(settings.ENABLE_METRICS_LOG),
        max_preview_chars=max_chars,
        include_preview=include_preview,
    )(func)

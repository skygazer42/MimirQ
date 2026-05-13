"""
Agent/workflow lifecycle logging middleware.

Reference implementation of `@before_agent` / `@after_agent`:
- Records start/end timestamps
- Calculates total elapsed time
- Captures success/fail + execution_path/iterations (when provided by runner)

This middleware is disabled by default (settings.AGENT_LOG_ENABLED).
"""

import time
from dataclasses import dataclass
from typing import Any

from app.core.config import settings
from app.rag.core.logging import get_logger
from app.rag.middleware.base import after_agent, before_agent
from app.services.metrics_logger import log_metrics

logger = get_logger("rag.middleware.agent_logging")


def _now_ts() -> float:
    return time.time()


def _safe_str(value: Any, max_chars: int) -> str:
    text = str(value) if value is not None else ""
    if max_chars > 0 and len(text) > max_chars:
        return text[:max_chars] + "..."
    return text


@dataclass
class AgentExecutionLoggingMiddleware:
    enabled: bool = False
    include_execution_path: bool = False
    max_preview_chars: int = 500

    def before(self, state: dict[str, Any]) -> dict[str, Any]:
        if not self.enabled:
            return state
        agent = dict(state.get("_agent") or {})
        agent["start_ts"] = _now_ts()
        state["_agent"] = agent
        return state

    def after(self, state: dict[str, Any]) -> dict[str, Any]:
        if not self.enabled:
            return state

        agent = dict(state.get("_agent") or {})
        start_ts = agent.get("start_ts")
        end_ts = _now_ts()
        elapsed_ms: float | None = None
        if isinstance(start_ts, (int, float)):
            elapsed_ms = round((end_ts - float(start_ts)) * 1000, 2)

        workflow_name = agent.get("workflow")
        workflow_mode = agent.get("mode")
        success = agent.get("success")
        error = agent.get("error")
        iterations = agent.get("iterations")
        execution_path = agent.get("execution_path") or []

        metrics = dict(state.get("metrics") or {})
        metrics["workflow_name"] = workflow_name
        metrics["workflow_mode"] = workflow_mode
        metrics["workflow_elapsed_ms"] = elapsed_ms
        metrics["workflow_success"] = success
        metrics["workflow_error"] = _safe_str(error, self.max_preview_chars) if error else None
        metrics["workflow_iterations"] = iterations
        metrics["workflow_steps"] = len(execution_path) if isinstance(execution_path, list) else None
        if self.include_execution_path and isinstance(execution_path, list):
            metrics["workflow_execution_path"] = execution_path
        state["metrics"] = metrics

        log_metrics(
            {
                "event": "workflow_done",
                "workflow": workflow_name,
                "mode": workflow_mode,
                "elapsed_ms": elapsed_ms,
                "success": success,
                "error": _safe_str(error, 200) if error else None,
                "iterations": iterations,
                "steps": len(execution_path) if isinstance(execution_path, list) else None,
            }
        )

        return state


@before_agent(priority=50, name="agent_logging_before")
def _agent_logging_before(state: dict[str, Any]) -> dict[str, Any]:
    mw = AgentExecutionLoggingMiddleware(
        enabled=bool(getattr(settings, "AGENT_LOG_ENABLED", False)),
        include_execution_path=bool(getattr(settings, "AGENT_LOG_INCLUDE_EXECUTION_PATH", False)),
        max_preview_chars=int(getattr(settings, "AGENT_LOG_MAX_PREVIEW_CHARS", 500) or 500),
    )
    return mw.before(state)


@after_agent(priority=50, name="agent_logging_after")
def _agent_logging_after(state: dict[str, Any]) -> dict[str, Any]:
    mw = AgentExecutionLoggingMiddleware(
        enabled=bool(getattr(settings, "AGENT_LOG_ENABLED", False)),
        include_execution_path=bool(getattr(settings, "AGENT_LOG_INCLUDE_EXECUTION_PATH", False)),
        max_preview_chars=int(getattr(settings, "AGENT_LOG_MAX_PREVIEW_CHARS", 500) or 500),
    )
    return mw.after(state)

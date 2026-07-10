"""
PII redaction middleware.

Implements lightweight detection/redaction for common sensitive patterns:
- Email
- Phone numbers (CN mobile)
- Chinese ID numbers
- Credit card-like numbers (Luhn-validated)
- Common API key/token formats (e.g. sk-...)

This middleware is disabled by default (see settings.PII_REDACTION_ENABLED).
"""



from typing import Any

from app.core.pii_redaction import PIIRedactor
from app.core.pii_redaction import pii_redaction_enabled as _pii_redaction_enabled
from app.core.pii_redaction import redact_obj as _redact_obj
from app.core.pii_redaction import redact_text as _redact_text
from app.rag.middleware.base import (
    after_model,
    after_tool_call,
    before_model,
    before_tool_call,
)


def pii_enabled() -> bool:
    return bool(_pii_redaction_enabled())


class PIIMiddleware:
    """
    Public middleware facade.

    The actual redaction hooks are registered via decorators in this module.
    This class is mainly for reuse by callers that want explicit redaction.
    """

    def __init__(self, redactor: PIIRedactor | None = None) -> None:
        # Kept for API compatibility; core redaction uses a cached, settings-driven redactor.
        self.redactor = redactor or PIIRedactor()

    def enabled(self) -> bool:
        return pii_enabled()

    def redact_text(self, text: str) -> str:
        return redact_text(text)

    def redact_obj(self, obj: Any) -> Any:
        return redact_obj(obj)


def redact_text(text: str) -> str:
    """Convenience wrapper (no meta)."""
    return _redact_text(text)


def redact_obj(obj: Any) -> Any:
    return _redact_obj(obj)


@before_tool_call(priority=20, name="pii_before_tool_call")
def _pii_before_tool_call(state: dict[str, Any]) -> dict[str, Any]:
    if not pii_enabled():
        return state
    args = state.get("arguments") or {}
    state["arguments"] = redact_obj(args)
    return state


@after_tool_call(priority=20, name="pii_after_tool_call")
def _pii_after_tool_call(state: dict[str, Any]) -> dict[str, Any]:
    if not pii_enabled():
        return state
    state["result"] = redact_obj(state.get("result"))
    if state.get("error"):
        state["error"] = redact_text(str(state.get("error")))
    return state


@before_model(priority=20, name="pii_before_model")
def _pii_before_model(state: dict[str, Any]) -> dict[str, Any]:
    """
    Best-effort redaction for model inputs.

    This is intentionally conservative and only touches common string fields.
    """
    if not pii_enabled():
        return state

    for key in ("question", "query", "history", "context", "system_prompt", "prompt"):
        if key not in state:
            continue
        state[key] = redact_obj(state.get(key))

    return state


@after_model(priority=20, name="pii_after_model")
def _pii_after_model(state: dict[str, Any]) -> dict[str, Any]:
    if not pii_enabled():
        return state
    for key in ("answer", "response", "output"):
        if key in state and isinstance(state.get(key), str):
            state[key] = redact_text(state[key])
    return state

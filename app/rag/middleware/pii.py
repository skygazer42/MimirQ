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

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Tuple

from app.core.config import settings
from app.rag.middleware.base import (
    after_model,
    after_tool_call,
    before_model,
    before_tool_call,
)

logger = logging.getLogger(__name__)


_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_CN_MOBILE_RE = re.compile(r"\b1[3-9]\d{9}\b")
_CN_ID_RE = re.compile(r"\b\d{17}[\dXx]\b")
_OPENAI_KEY_RE = re.compile(r"\bsk-[A-Za-z0-9]{20,}\b")
_AWS_ACCESS_KEY_RE = re.compile(r"\bAKIA[0-9A-Z]{16}\b")
_GENERIC_KV_SECRET_RE = re.compile(
    r"(?i)\b(api[_-]?key|apikey|access[_-]?key|secret|token|bearer)\b\s*[:=]\s*([^\s,;]{8,})"
)
_CARD_CANDIDATE_RE = re.compile(r"\b(?:\d[ -]*?){13,19}\b")


def _luhn_ok(digits: str) -> bool:
    nums = [int(ch) for ch in digits if ch.isdigit()]
    if not (13 <= len(nums) <= 19):
        return False

    total = 0
    parity = len(nums) % 2
    for idx, d in enumerate(nums):
        if idx % 2 == parity:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


@dataclass
class PIIRedactor:
    mask: str = "[REDACTED]"

    def redact_text(self, text: str) -> Tuple[str, Dict[str, Any]]:
        raw = str(text or "")
        meta: Dict[str, Any] = {"redacted": False, "hits": {}}

        def _mark(kind: str, n: int = 1) -> None:
            meta["redacted"] = True
            hits = meta["hits"]
            hits[kind] = int(hits.get(kind, 0) or 0) + int(n or 0)

        out = raw

        # Key/value style secrets: keep the key name but mask the value.
        def _kv_repl(match: re.Match) -> str:
            _mark("secret_kv")
            return f"{match.group(1)}={self.mask}"

        out, _ = _GENERIC_KV_SECRET_RE.subn(_kv_repl, out)

        for kind, pattern in (
            ("openai_key", _OPENAI_KEY_RE),
            ("aws_access_key", _AWS_ACCESS_KEY_RE),
            ("email", _EMAIL_RE),
            ("cn_mobile", _CN_MOBILE_RE),
            ("cn_id", _CN_ID_RE),
        ):
            out, n = pattern.subn(self.mask, out)
            if n:
                _mark(kind, n)

        # Credit card candidates: validate with Luhn to reduce false positives.
        def _card_repl(match: re.Match) -> str:
            s = match.group(0) or ""
            digits = "".join(ch for ch in s if ch.isdigit())
            if _luhn_ok(digits):
                _mark("credit_card")
                return self.mask
            return s

        out = _CARD_CANDIDATE_RE.sub(_card_repl, out)
        return out, meta

    def redact_obj(self, obj: Any) -> Any:
        if obj is None:
            return obj
        if isinstance(obj, str):
            return self.redact_text(obj)[0]
        if isinstance(obj, dict):
            return {k: self.redact_obj(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            redacted = [self.redact_obj(v) for v in obj]
            return type(obj)(redacted) if isinstance(obj, tuple) else redacted
        return obj


_redactor = PIIRedactor(mask=getattr(settings, "PII_REDACTION_MASK", "[REDACTED]") or "[REDACTED]")


def pii_enabled() -> bool:
    return bool(getattr(settings, "PII_REDACTION_ENABLED", False))


class PIIMiddleware:
    """
    Public middleware facade.

    The actual redaction hooks are registered via decorators in this module.
    This class is mainly for reuse by callers that want explicit redaction.
    """

    def __init__(self, redactor: PIIRedactor | None = None) -> None:
        self.redactor = redactor or _redactor

    def enabled(self) -> bool:
        return pii_enabled()

    def redact_text(self, text: str) -> str:
        return redact_text(text)

    def redact_obj(self, obj: Any) -> Any:
        return redact_obj(obj)


def redact_text(text: str) -> str:
    """Convenience wrapper (no meta)."""
    if not pii_enabled():
        return text
    return _redactor.redact_text(text)[0]


def redact_obj(obj: Any) -> Any:
    if not pii_enabled():
        return obj
    return _redactor.redact_obj(obj)


@before_tool_call(priority=20, name="pii_before_tool_call")
def _pii_before_tool_call(state: Dict[str, Any]) -> Dict[str, Any]:
    if not pii_enabled():
        return state
    args = state.get("arguments") or {}
    state["arguments"] = redact_obj(args)
    return state


@after_tool_call(priority=20, name="pii_after_tool_call")
def _pii_after_tool_call(state: Dict[str, Any]) -> Dict[str, Any]:
    if not pii_enabled():
        return state
    state["result"] = redact_obj(state.get("result"))
    if state.get("error"):
        state["error"] = redact_text(str(state.get("error")))
    return state


@before_model(priority=20, name="pii_before_model")
def _pii_before_model(state: Dict[str, Any]) -> Dict[str, Any]:
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
def _pii_after_model(state: Dict[str, Any]) -> Dict[str, Any]:
    if not pii_enabled():
        return state
    for key in ("answer", "response", "output"):
        if key in state and isinstance(state.get(key), str):
            state[key] = redact_text(state[key])
    return state

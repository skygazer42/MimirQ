"""
PII redaction helpers (dependency-free).

This module is intentionally located under app.core to avoid import cycles and to
ensure PII_REDACTION_ENABLED cannot be silently bypassed by internal try-imports.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from app.core.config import settings
from app.rag.core.logging import get_logger

logger = get_logger("core.pii_redaction")
DEFAULT_MASK = "[REDACTED]"

_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_CN_MOBILE_RE = re.compile(r"\b1[3-9]\d{9}\b")
_CN_ID_RE = re.compile(r"\b\d{17}[\dXx]\b")
_OPENAI_KEY_RE = re.compile(r"\bsk-[A-Za-z0-9]{20,}\b")
_AWS_ACCESS_KEY_RE = re.compile(r"\bAKIA[0-9A-Z]{16}\b")
_GENERIC_KV_SECRET_RE = re.compile(
    r"(?i)\b(api[_-]?key|access[_-]?key|secret|token|bearer)\b\s*[:=]\s*([^\s,;]{8,})"
)
_CARD_CANDIDATE_RE = re.compile(r"\b(?:\d[ -]*){13,19}\b")


def pii_redaction_enabled() -> bool:
    return bool(getattr(settings, "PII_REDACTION_ENABLED", False))


def _current_mask() -> str:
    mask = str(getattr(settings, "PII_REDACTION_MASK", DEFAULT_MASK) or DEFAULT_MASK).strip()
    return mask or DEFAULT_MASK


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
    mask: str = DEFAULT_MASK

    def redact_text(self, text: str) -> tuple[str, dict[str, Any]]:
        raw = str(text or "")
        meta: dict[str, Any] = {"redacted": False, "hits": {}}

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


@lru_cache(maxsize=8)
def _get_redactor(mask: str) -> PIIRedactor:
    normalized_mask = str(mask or DEFAULT_MASK).strip() or DEFAULT_MASK
    return PIIRedactor(mask=normalized_mask)


def redact_text(text: str) -> str:
    """Convenience wrapper (no meta)."""
    if not pii_redaction_enabled():
        return text
    try:
        return _get_redactor(_current_mask()).redact_text(text)[0]
    except Exception as exc:  # noqa: BLE001
        # Fail-closed: do not emit raw content when redaction is enabled.
        logger.exception(
            "PII redaction failed; content masked: feature=%s reason=%s error=%s",
            "pii_redaction",
            "exception",
            str(exc)[:200],
        )
        return _current_mask() if (text or "") else text


def redact_obj(obj: Any) -> Any:
    if not pii_redaction_enabled():
        return obj
    try:
        return _get_redactor(_current_mask()).redact_obj(obj)
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "PII redaction failed; object masked: feature=%s reason=%s error=%s",
            "pii_redaction",
            "exception",
            str(exc)[:200],
        )
        # Best-effort fail-closed: preserve containers, mask strings.
        if isinstance(obj, str):
            return _current_mask()
        if isinstance(obj, dict):
            return {k: _current_mask() if isinstance(v, str) else v for k, v in obj.items()}
        if isinstance(obj, list):
            return [_current_mask() if isinstance(v, str) else v for v in obj]
        if isinstance(obj, tuple):
            return tuple(_current_mask() if isinstance(v, str) else v for v in obj)
        return _current_mask()


__all__ = [
    "PIIRedactor",
    "pii_redaction_enabled",
    "redact_obj",
    "redact_text",
]

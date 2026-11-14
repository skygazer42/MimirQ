"""
Runtime regex guards (server-side).

Goal:
- Provide best-effort timeouts for regex substitutions to reduce ReDoS risk.
- Keep the calling layer (governance/pipeline) responsible for surfacing errors.

Notes:
- Uses the third-party `regex` module (if available) to enforce timeouts.
- Falls back to Python's built-in `re` when `regex` isn't available or when the
  replacement is a callable (match-type differences across engines).
"""

import re
from collections.abc import Callable
from typing import Any

from app.core.optional_deps import optional_import

_regex = optional_import("regex", feature="governance_regex_timeout")


DEFAULT_REGEX_TIMEOUT_MS = 100


class RegexSubstitutionTimeoutError(RuntimeError):
    def __init__(self, *, rule_index: int, pattern: str, timeout_ms: int) -> None:
        super().__init__(f"regex_timeout (rule_index={rule_index}, timeout_ms={timeout_ms})")
        self.rule_index = rule_index
        self.pattern = pattern
        self.timeout_ms = timeout_ms

    def to_detail(self) -> dict[str, Any]:
        return {
            "code": "regex_timeout",
            "message": str(self) or "regex timed out",
            "rule_index": self.rule_index,
            "pattern": self.pattern[:300],
            "timeout_ms": self.timeout_ms,
        }


def safe_subn(
    *,
    pattern: str,
    repl: str | Callable[[re.Match[str]], str],
    text: str,
    flags: int = 0,
    timeout_ms: int | None = None,
    rule_index: int = -1,
) -> tuple[str, int]:
    """
    Safe-ish regex substitution wrapper with an optional timeout.

    - When `timeout_ms` <= 0: no timeout is enforced.
    - When `regex` is unavailable: falls back to `re.subn` (no timeout).
    - When `repl` is callable: falls back to `re.subn` to keep match-type consistent.
    """
    timeout = DEFAULT_REGEX_TIMEOUT_MS if timeout_ms is None else timeout_ms
    timeout = max(0, timeout)
    if timeout <= 0 or _regex is None or callable(repl):
        return re.subn(pattern, repl, text, flags=flags)

    try:
        return _regex.subn(pattern, repl, text, flags=flags, timeout=timeout / 1000.0)
    except TimeoutError as exc:
        raise RegexSubstitutionTimeoutError(rule_index=rule_index, pattern=pattern, timeout_ms=timeout) from exc


__all__ = [
    "DEFAULT_REGEX_TIMEOUT_MS",
    "RegexSubstitutionTimeoutError",
    "safe_subn",
]

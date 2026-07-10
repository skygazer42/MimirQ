"""
Regex safety validation utilities (server-side).

These helpers are used to validate user-provided regex rules (e.g. governance profiles,
pipeline clean-preview custom rules) to reduce ReDoS risk and keep payloads bounded.
"""


import re
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any

DEFAULT_MAX_RULES = 60
DEFAULT_MAX_PATTERN_LEN = 600
DEFAULT_MAX_REPL_LEN = 2000
DEFAULT_ALLOWED_FLAG_BITS = int(re.IGNORECASE | re.MULTILINE | re.DOTALL)


def looks_like_nested_quantifier(pattern: str) -> bool:
    """
    Detect a common nested-quantifier shape:
      (...+ ...)+  or  (...* ...)*  (very rough)

    This mirrors the previous regex-based heuristic:
      \\([^)]*[+*][^)]*\\)[+*]

    Notes:
    - This is intentionally conservative and does not attempt to parse full regex grammar.
    - It is used as a best-effort guardrail for *user-provided* patterns.
    """
    s = str(pattern or "")
    if not s:
        return False

    i = 0
    escaped = False
    n = len(s)

    while i < n:
        ch = s[i]
        if escaped:
            escaped = False
            i += 1
            continue
        if ch == "\\":
            escaped = True
            i += 1
            continue

        if ch != "(":
            i += 1
            continue

        # Scan forward to the next unescaped ')', tracking whether the group
        # contains an unescaped '+' or '*'.
        j = i + 1
        inner_escaped = False
        inner_has_quant = False
        while j < n:
            cj = s[j]
            if inner_escaped:
                inner_escaped = False
                j += 1
                continue
            if cj == "\\":
                inner_escaped = True
                j += 1
                continue
            if cj == ")":
                break
            if cj in {"+", "*"}:
                inner_has_quant = True
            j += 1

        if j < n and s[j] == ")":
            if inner_has_quant and j + 1 < n and s[j + 1] in {"+", "*"}:
                return True

        i = j + 1

    return False


def _has_suspicious_nested_quantifier(pattern: str) -> bool:
    # Backwards-compatible private alias used by validate_regex_rules.
    return looks_like_nested_quantifier(pattern)


@dataclass(frozen=True)
class RegexRuleViolation:
    index: int
    field: str
    code: str
    message: str


class RegexRulesValidationError(ValueError):
    def __init__(self, message: str, *, errors: list[RegexRuleViolation] | None = None) -> None:
        super().__init__(message)
        self._errors = list(errors or [])

    @property
    def errors(self) -> list[RegexRuleViolation]:
        return list(self._errors)

    def to_detail(self) -> dict[str, Any]:
        return {
            "code": "regex_rules_invalid",
            "message": str(self) or "regex rules invalid",
            "errors": [asdict(e) for e in (self._errors or [])],
        }


def _get_field(item: Any, key: str) -> Any:
    if isinstance(item, Mapping):
        return item.get(key)
    return getattr(item, key, None)


def validate_regex_rules(
    rules: Any,
    *,
    max_rules: int = DEFAULT_MAX_RULES,
    max_pattern_len: int = DEFAULT_MAX_PATTERN_LEN,
    max_repl_len: int = DEFAULT_MAX_REPL_LEN,
    allowed_flag_bits: int = DEFAULT_ALLOWED_FLAG_BITS,
) -> list[dict[str, Any]]:
    """
    Validate and normalize a list of regex rules.

    Input:
    - rules: list of objects/dicts with keys/attrs: pattern, repl, flags

    Output:
    - list of {pattern, repl, flags} dicts (validated and safe-ish)

    Raises:
    - RegexRulesValidationError with structured `errors` payload.
    """
    if rules is None:
        return []

    if isinstance(rules, (str, bytes)):
        raise RegexRulesValidationError(
            "regex rules must be a list",
            errors=[
                RegexRuleViolation(index=-1, field="rules", code="type", message="expected list"),
            ],
        )

    if not isinstance(rules, Sequence):
        raise RegexRulesValidationError(
            "regex rules must be a list",
            errors=[
                RegexRuleViolation(index=-1, field="rules", code="type", message="expected list"),
            ],
        )

    items = list(rules)
    limit = max(0, int(max_rules or 0))
    if limit and len(items) > limit:
        raise RegexRulesValidationError(
            f"too many regex rules (max={limit})",
            errors=[RegexRuleViolation(index=-1, field="rules", code="too_many", message=f"max={limit}")],
        )

    normalized: list[dict[str, Any]] = []
    violations: list[RegexRuleViolation] = []

    for idx, item in enumerate(items):
        pat_raw = _get_field(item, "pattern")
        repl_raw = _get_field(item, "repl")
        flags_raw = _get_field(item, "flags")

        pat = str(pat_raw or "")
        if not pat.strip():
            violations.append(
                RegexRuleViolation(index=idx, field="pattern", code="required", message="pattern is required")
            )
            continue

        if max_pattern_len and len(pat) > int(max_pattern_len):
            violations.append(
                RegexRuleViolation(
                    index=idx,
                    field="pattern",
                    code="too_long",
                    message=f"max_len={int(max_pattern_len)}",
                )
            )
            continue

        if _has_suspicious_nested_quantifier(pat):
            violations.append(
                RegexRuleViolation(index=idx, field="pattern", code="unsafe", message="nested quantifier")
            )
            continue

        repl = str(repl_raw or "")
        if max_repl_len and len(repl) > int(max_repl_len):
            violations.append(
                RegexRuleViolation(
                    index=idx,
                    field="repl",
                    code="too_long",
                    message=f"max_len={int(max_repl_len)}",
                )
            )
            continue

        try:
            flags = int(flags_raw or 0)
        except (TypeError, ValueError):
            violations.append(
                RegexRuleViolation(index=idx, field="flags", code="invalid", message="flags must be int")
            )
            continue

        if flags < 0:
            violations.append(
                RegexRuleViolation(index=idx, field="flags", code="invalid", message="flags must be >= 0")
            )
            continue

        if int(allowed_flag_bits) and (flags & ~int(allowed_flag_bits)):
            violations.append(
                RegexRuleViolation(index=idx, field="flags", code="unsupported", message="unsupported flag bits")
            )
            continue

        try:
            re.compile(pat, flags=flags)
        except re.error as exc:
            violations.append(
                RegexRuleViolation(index=idx, field="pattern", code="compile_error", message=str(exc)[:200])
            )
            continue

        normalized.append({"pattern": pat, "repl": repl, "flags": flags})

    if violations:
        raise RegexRulesValidationError("invalid regex rules", errors=violations)

    return normalized


__all__ = [
    "DEFAULT_ALLOWED_FLAG_BITS",
    "DEFAULT_MAX_PATTERN_LEN",
    "DEFAULT_MAX_REPL_LEN",
    "DEFAULT_MAX_RULES",
    "RegexRuleViolation",
    "RegexRulesValidationError",
    "looks_like_nested_quantifier",
    "validate_regex_rules",
]

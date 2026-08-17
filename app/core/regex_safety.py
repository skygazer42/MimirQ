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


def _scan_group_body(pattern: str, start: int) -> tuple[int, bool]:
    index = start + 1
    escaped = False
    contains_quantifier = False
    while index < len(pattern):
        char = pattern[index]
        if escaped:
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == ")":
            break
        elif char in {"+", "*"}:
            contains_quantifier = True
        index += 1
    return index, contains_quantifier


def _group_has_outer_quantifier(pattern: str, close_index: int, contains_quantifier: bool) -> bool:
    return (
        contains_quantifier
        and close_index < len(pattern)
        and pattern[close_index] == ")"
        and close_index + 1 < len(pattern)
        and pattern[close_index + 1] in {"+", "*"}
    )


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

        j, inner_has_quant = _scan_group_body(s, i)
        if _group_has_outer_quantifier(s, j, inner_has_quant):
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


def _rules_sequence(rules: Any, *, max_rules: int) -> list[Any]:
    if isinstance(rules, (str, bytes)) or not isinstance(rules, Sequence):
        raise RegexRulesValidationError(
            "regex rules must be a list",
            errors=[RegexRuleViolation(index=-1, field="rules", code="type", message="expected list")],
        )
    items = list(rules)
    limit = max(0, int(max_rules or 0))
    if limit and len(items) > limit:
        raise RegexRulesValidationError(
            f"too many regex rules (max={limit})",
            errors=[RegexRuleViolation(index=-1, field="rules", code="too_many", message=f"max={limit}")],
        )
    return items


def _validate_pattern(index: int, raw_pattern: Any, *, max_pattern_len: int) -> tuple[str, RegexRuleViolation | None]:
    pattern = str(raw_pattern or "")
    if not pattern.strip():
        return pattern, RegexRuleViolation(
            index=index,
            field="pattern",
            code="required",
            message="pattern is required",
        )
    if max_pattern_len and len(pattern) > int(max_pattern_len):
        return pattern, RegexRuleViolation(
            index=index,
            field="pattern",
            code="too_long",
            message=f"max_len={int(max_pattern_len)}",
        )
    if _has_suspicious_nested_quantifier(pattern):
        return pattern, RegexRuleViolation(
            index=index,
            field="pattern",
            code="unsafe",
            message="nested quantifier",
        )
    return pattern, None


def _validate_replacement(
    index: int, raw_replacement: Any, *, max_repl_len: int
) -> tuple[str, RegexRuleViolation | None]:
    replacement = str(raw_replacement or "")
    if max_repl_len and len(replacement) > int(max_repl_len):
        return replacement, RegexRuleViolation(
            index=index,
            field="repl",
            code="too_long",
            message=f"max_len={int(max_repl_len)}",
        )
    return replacement, None


def _validate_flags(index: int, raw_flags: Any, *, allowed_flag_bits: int) -> tuple[int, RegexRuleViolation | None]:
    try:
        flags = int(raw_flags or 0)
    except (TypeError, ValueError):
        return 0, RegexRuleViolation(
            index=index,
            field="flags",
            code="invalid",
            message="flags must be int",
        )
    if flags < 0:
        return flags, RegexRuleViolation(
            index=index,
            field="flags",
            code="invalid",
            message="flags must be >= 0",
        )
    if int(allowed_flag_bits) and (flags & ~int(allowed_flag_bits)):
        return flags, RegexRuleViolation(
            index=index,
            field="flags",
            code="unsupported",
            message="unsupported flag bits",
        )
    return flags, None


def _normalize_regex_rule(
    index: int,
    item: Any,
    *,
    max_pattern_len: int,
    max_repl_len: int,
    allowed_flag_bits: int,
) -> tuple[dict[str, Any] | None, RegexRuleViolation | None]:
    pattern, violation = _validate_pattern(
        index,
        _get_field(item, "pattern"),
        max_pattern_len=max_pattern_len,
    )
    if violation is not None:
        return None, violation
    replacement, violation = _validate_replacement(
        index,
        _get_field(item, "repl"),
        max_repl_len=max_repl_len,
    )
    if violation is not None:
        return None, violation
    flags, violation = _validate_flags(
        index,
        _get_field(item, "flags"),
        allowed_flag_bits=allowed_flag_bits,
    )
    if violation is not None:
        return None, violation
    try:
        re.compile(pattern, flags=flags)
    except re.error as exc:
        return None, RegexRuleViolation(
            index=index,
            field="pattern",
            code="compile_error",
            message=str(exc)[:200],
        )
    return {"pattern": pattern, "repl": replacement, "flags": flags}, None


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
    items = _rules_sequence(rules, max_rules=max_rules)
    normalized: list[dict[str, Any]] = []
    violations: list[RegexRuleViolation] = []
    for idx, item in enumerate(items):
        rule, violation = _normalize_regex_rule(
            idx,
            item,
            max_pattern_len=max_pattern_len,
            max_repl_len=max_repl_len,
            allowed_flag_bits=allowed_flag_bits,
        )
        if violation is not None:
            violations.append(violation)
        elif rule is not None:
            normalized.append(rule)
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

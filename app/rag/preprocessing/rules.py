
from app.rag.preprocessing.cleaning import RegexRule
from app.rag.preprocessing.rule_packs import GOVERNANCE_RULE_PACKS

DEFAULT_MARKDOWN_RULES: list[RegexRule] = [
    # Normalize common "page X" footer artifacts (conservative).
    RegexRule(pattern=r"(?m)^[ \t]*Page[ \t]+\d+[ \t]*$", repl="", flags=0),
    RegexRule(pattern=r"(?m)^[ \t]*Page[ \t]+\d+[ \t]*(?:/|of)[ \t]*\d+[ \t]*$", repl="", flags=0),
    RegexRule(pattern=r"(?m)^[ \t]*第[ \t]*\d+[ \t]*页[ \t]*$", repl="", flags=0),
    RegexRule(pattern=r"(?m)^[ \t]*第[ \t]*\d+[ \t]*页[ \t]*/[ \t]*共[ \t]*\d+[ \t]*页[ \t]*$", repl="", flags=0),
    RegexRule(pattern=r"(?m)^[ \t]*\d+[ \t]*/[ \t]*\d+[ \t]*$", repl="", flags=0),
    # Page number wrapped by dashes (common in PDF exports): "— 12 —" / "- 3 -".
    RegexRule(pattern=r"(?m)^[ \t]*[-\u2013\u2014]{1,6}[ \t]*\d{1,4}[ \t]*[-\u2013\u2014]{1,6}[ \t]*$", repl="", flags=0),
    # Remove excessive horizontal separators from some exporters.
    RegexRule(pattern=r"(?m)^[ \t]*[-=_]{8,}[ \t]*$", repl="", flags=0),
    RegexRule(pattern=r"(?m)^[ \t]*[.\u00b7]{6,}[ \t]*$", repl="", flags=0),
    # Microsoft Word template / field artifacts (conservative full-line matches).
    RegexRule(pattern=r"(?mi)^[ \t]*error!\s*reference\s*source\s*not\s*found\.?[ \t]*$", repl="", flags=0),
    RegexRule(pattern=r"(?mi)^[ \t]*error!\s*bookmark\s*not\s*defined\.?[ \t]*$", repl="", flags=0),
    RegexRule(pattern=r"(?m)^[ \t]*错误!\s*未找到引用源。?[ \t]*$", repl="", flags=0),
    RegexRule(pattern=r"(?m)^[ \t]*错误!\s*未定义书签。?[ \t]*$", repl="", flags=0),
    RegexRule(pattern=r"(?mi)^[ \t]*click\s+here\s+to\s+enter\s+text\.?[ \t]*$", repl="", flags=0),
    RegexRule(pattern=r"(?m)^[ \t]*(?:单击|点击)此处输入文本。?[ \t]*$", repl="", flags=0),
    # Common footer noise (single-line).
    RegexRule(pattern=r"(?mi)^[ \t]*(confidential|internal use only|for internal use only)[ \t]*$", repl="", flags=0),
    RegexRule(pattern=r"(?mi)^[ \t]*copyright[ \t]*\u00a9?[ \t]*\d{4}.*$", repl="", flags=0),
    RegexRule(pattern=r"(?mi)^[ \t]*all rights reserved\.?[ \t]*$", repl="", flags=0),
    RegexRule(pattern=r"(?m)^[ \t]*\u7248\u6743\u6240\u6709.*$", repl="", flags=0),
]


def _extend_rule_packs(out: list[RegexRule], rule_packs: list[str] | None) -> None:
    seen: set[str] = set()
    for raw in rule_packs or []:
        if not isinstance(raw, str):
            continue
        key = raw.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        pack = GOVERNANCE_RULE_PACKS.get(key)
        if pack:
            out.extend(list(pack))


def _coerce_extra_rule(item: object) -> RegexRule | None:
    if not isinstance(item, dict):
        return None
    pat = item.get("pattern")
    if not isinstance(pat, str) or not pat.strip():
        return None
    repl = item.get("repl", "")
    if repl is None:
        repl = ""
    flags = item.get("flags", 0)
    try:
        flags_int = int(flags)
    except Exception:
        flags_int = 0
    return RegexRule(pattern=pat, repl=str(repl), flags=flags_int)


def build_governance_rules(
    extra_rules: list[dict] | None = None,
    *,
    rule_packs: list[str] | None = None,
) -> list[RegexRule]:
    """
    Combine default governance rules with optional rule packs and extra user-provided rules (best-effort).

    Notes:
    - rule_packs are server-defined presets (declarative) and should be sanitized earlier.
    - extra_rules should be sanitized earlier (pipeline_config / profile validation).
    - Caller may skip passing rules when extra_rules is empty, allowing the processor
      to reuse its internal defaults.
    """
    out = list(DEFAULT_MARKDOWN_RULES)
    _extend_rule_packs(out, rule_packs)
    for item in (extra_rules or []):
        rule = _coerce_extra_rule(item)
        if rule is not None:
            out.append(rule)
    return out

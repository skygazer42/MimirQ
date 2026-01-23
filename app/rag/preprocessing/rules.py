
from app.rag.preprocessing.cleaning import RegexRule


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
    # Common footer noise (single-line).
    RegexRule(pattern=r"(?mi)^[ \t]*(confidential|internal use only|for internal use only)[ \t]*$", repl="", flags=0),
    RegexRule(pattern=r"(?mi)^[ \t]*copyright[ \t]*\u00a9?[ \t]*\d{4}.*$", repl="", flags=0),
    RegexRule(pattern=r"(?mi)^[ \t]*all rights reserved\.?[ \t]*$", repl="", flags=0),
    RegexRule(pattern=r"(?m)^[ \t]*\u7248\u6743\u6240\u6709.*$", repl="", flags=0),
]


def build_governance_rules(extra_rules: list[dict] | None = None) -> list[RegexRule]:
    """
    Combine default governance rules with extra user-provided rules (best-effort).

    Notes:
    - extra_rules should be sanitized earlier (pipeline_config / profile validation).
    - Caller may skip passing rules when extra_rules is empty, allowing the processor
      to reuse its internal defaults.
    """
    out = list(DEFAULT_MARKDOWN_RULES)
    for item in (extra_rules or []):
        if not isinstance(item, dict):
            continue
        pat = item.get("pattern")
        if not isinstance(pat, str) or not pat.strip():
            continue
        repl = item.get("repl", "")
        if repl is None:
            repl = ""
        flags = item.get("flags", 0)
        try:
            flags_int = int(flags)
        except Exception:
            flags_int = 0
        out.append(RegexRule(pattern=pat, repl=str(repl), flags=flags_int))
    return out

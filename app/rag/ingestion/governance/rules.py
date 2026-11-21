from typing import Any

from app.rag.ingestion.governance.cleaning import RegexRule
from app.rag.ingestion.governance.rule_packs import GOVERNANCE_RULE_PACKS

DEFAULT_MARKDOWN_RULES: list[RegexRule] = [
    # Normalize common "page X" footer artifacts (conservative).
    RegexRule(pattern=r"(?m)^[ \t]*Page[ \t]+\d+[ \t]*$", repl="", flags=0),
    RegexRule(pattern=r"(?m)^[ \t]*Page[ \t]+\d+[ \t]*(?:/|of)[ \t]*\d+[ \t]*$", repl="", flags=0),
    RegexRule(pattern=r"(?m)^[ \t]*第[ \t]*\d+[ \t]*页[ \t]*$", repl="", flags=0),
    RegexRule(pattern=r"(?m)^[ \t]*第[ \t]*\d+[ \t]*页[ \t]*/[ \t]*共[ \t]*\d+[ \t]*页[ \t]*$", repl="", flags=0),
    RegexRule(pattern=r"(?m)^[ \t]*\d+[ \t]*/[ \t]*\d+[ \t]*$", repl="", flags=0),
    # Page number wrapped by dashes (common in PDF exports): "— 12 —" / "- 3 -".
    RegexRule(
        pattern=r"(?m)^[ \t]*[-\u2013\u2014]{1,6}[ \t]*\d{1,4}[ \t]*[-\u2013\u2014]{1,6}[ \t]*$", repl="", flags=0
    ),
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


def build_governance_rules(
    extra_rules: list[dict[str, Any]] | None = None,
    *,
    rule_packs: list[str] | None = None,
) -> list[RegexRule]:
    """
    Combine preset rules with extra rules already validated by pipeline configuration.
    """
    out = list(DEFAULT_MARKDOWN_RULES)
    seen: set[str] = set()
    for name in rule_packs if rule_packs is not None else ():
        key = name.strip().lower()
        if key in seen:
            continue
        seen.add(key)
        out.extend(GOVERNANCE_RULE_PACKS.get(key, ()))
    if extra_rules is not None:
        out.extend(RegexRule(**item) for item in extra_rules)
    return out

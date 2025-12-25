from __future__ import annotations

from app.governance.cleaning import RegexRule


DEFAULT_MARKDOWN_RULES: list[RegexRule] = [
    # Normalize common "page X" footer artifacts (conservative).
    RegexRule(pattern=r"(?m)^[ \t]*Page[ \t]+\d+[ \t]*$", repl="", flags=0),
    RegexRule(pattern=r"(?m)^[ \t]*第[ \t]*\d+[ \t]*页[ \t]*$", repl="", flags=0),
    # Remove excessive horizontal separators from some exporters.
    RegexRule(pattern=r"(?m)^[ \t]*[-=_]{8,}[ \t]*$", repl="", flags=0),
]

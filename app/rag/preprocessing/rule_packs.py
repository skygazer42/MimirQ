"""
Named governance rule packs.

Rule packs are *optional* presets that expand into additional RegexRule entries.
They are disabled by default and must be explicitly enabled via pipeline options
or governance profiles.
"""

from __future__ import annotations

from app.rag.preprocessing.cleaning import RegexRule


# Keep rule packs conservative and line-oriented. Prefer anchored patterns to avoid
# removing real content in the middle of paragraphs.
GOVERNANCE_RULE_PACKS: dict[str, list[RegexRule]] = {
    "web_cookie_banners": [
        # Headings / banners.
        RegexRule(pattern=r"(?mi)^\s*cookie\s+consent\b.*$", repl="", flags=0),
        # Common banner lines.
        RegexRule(pattern=r"(?mi)^\s*we\s+use\s+cookies?\b.*$", repl="", flags=0),
        RegexRule(pattern=r"(?mi)^\s*this\s+(?:site|website)\s+uses\s+cookies?\b.*$", repl="", flags=0),
        RegexRule(pattern=r"(?mi)^\s*by\s+continuing\s+to\s+(?:use|browse|navigate)\b.*cookies?\b.*$", repl="", flags=0),
        # Button-like standalone lines.
        RegexRule(pattern=r"(?mi)^\s*(?:accept|agree|allow)\s+cookies?\s*$", repl="", flags=0),
        RegexRule(pattern=r"(?mi)^\s*(?:reject|decline)\s+cookies?\s*$", repl="", flags=0),
        RegexRule(pattern=r"(?mi)^\s*manage\s+(?:cookies?|preferences?)\s*$", repl="", flags=0),
    ],
}


def list_governance_rule_packs() -> list[str]:
    return sorted(GOVERNANCE_RULE_PACKS.keys())


__all__ = [
    "GOVERNANCE_RULE_PACKS",
    "list_governance_rule_packs",
]

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
    "email_disclaimer": [
        # Confidentiality / intended recipient.
        RegexRule(pattern=r"(?mi)^\s*this\s+(?:e-?mail|email|message)\b.*\bintended\b.*$", repl="", flags=0),
        RegexRule(pattern=r"(?mi)^\s*(?:and\s+)?may\s+contain\s+(?:confidential|privileged)\b.*$", repl="", flags=0),
        RegexRule(pattern=r"(?mi)^\s*if\s+you\s+are\s+not\s+(?:the\s+)?intended\s+recipient\b.*$", repl="", flags=0),
        RegexRule(pattern=r"(?mi)^\s*please\s+(?:notify|contact)\s+the\s+sender\b.*$", repl="", flags=0),
        RegexRule(pattern=r"(?mi)^\s*(?:delete|destroy)\s+(?:this\s+)?e-?mail\b.*$", repl="", flags=0),
        # Disclaimer about opinions / security.
        RegexRule(pattern=r"(?mi)^\s*any\s+views?\s+or\s+opinions?\s+(?:presented|expressed)\b.*$", repl="", flags=0),
        RegexRule(pattern=r"(?mi)^\s*e-?mail\s+transmission\s+cannot\s+be\s+guaranteed\b.*$", repl="", flags=0),
    ],
    "web_navigation": [
        # Common navigation prompts.
        RegexRule(pattern=r"(?mi)^\s*(?:skip|jump)\s+to\s+content\s*$", repl="", flags=0),
        RegexRule(pattern=r"(?mi)^\s*back\s+to\s+top\s*$", repl="", flags=0),
        # Share blocks / buttons (line-oriented).
        RegexRule(pattern=r"(?mi)^\s*share\s+this\b.*$", repl="", flags=0),
        RegexRule(pattern=r"(?mi)^\s*share\s+on\s+(?:twitter|x|facebook|linkedin)\b.*$", repl="", flags=0),
        # Breadcrumb-like headers ("Home / ...", "Home > ...", "Home » ...").
        RegexRule(pattern=r"(?mi)^\s*home\s*(?:/|>|»|\|)\s*\S.+$", repl="", flags=0),
    ],
    "pdf_watermark": [
        # Watermark-like full-line stamps (keep conservative).
        RegexRule(pattern=r"(?mi)^\s*draft\s*$", repl="", flags=0),
        RegexRule(pattern=r"(?mi)^\s*(?:company\s+)?confidential\s*$", repl="", flags=0),
        RegexRule(pattern=r"(?mi)^\s*strictly\s+confidential\s*$", repl="", flags=0),
        RegexRule(pattern=r"(?mi)^\s*internal\s+only\s*$", repl="", flags=0),
        RegexRule(pattern=r"(?mi)^\s*for\s+internal\s+use\s+only\s*$", repl="", flags=0),
        # Chinese (common PDF exports).
        RegexRule(pattern=r"(?m)^\s*(?:机密|保密|内部资料|内部使用|仅供内部使用)\s*$", repl="", flags=0),
    ],
}


def list_governance_rule_packs() -> list[str]:
    return sorted(GOVERNANCE_RULE_PACKS.keys())


__all__ = [
    "GOVERNANCE_RULE_PACKS",
    "list_governance_rule_packs",
]

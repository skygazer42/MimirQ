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
    "chat_export_noise": [
        # Slack/Teams export headers/footers and navigation prompts.
        RegexRule(pattern=r"(?mi)^\s*(?:slack\s+export|exported\s+from\s+slack)\b.*$", repl="", flags=0),
        RegexRule(pattern=r"(?mi)^\s*(?:microsoft\s+teams\s+export|exported\s+from\s+microsoft\s+teams)\b.*$", repl="", flags=0),
        RegexRule(pattern=r"(?mi)^\s*view\s+in\s+(?:slack|teams|microsoft\s+teams)\s*$", repl="", flags=0),
        RegexRule(pattern=r"(?mi)^\s*(?:jump|go)\s+to\s+message\s*$", repl="", flags=0),
        RegexRule(pattern=r"(?mi)^\s*reply\s+in\s+thread\s*$", repl="", flags=0),
        # Common system message noise (line-oriented).
        RegexRule(pattern=r"(?mi)^\s*.*\bhas\s+joined\s+the\s+channel\b.*$", repl="", flags=0),
        RegexRule(pattern=r"(?mi)^\s*.*\bhas\s+left\s+the\s+channel\b.*$", repl="", flags=0),
        # Timestamp-only lines (keep conservative: only time/date alone on a line).
        RegexRule(pattern=r"(?mi)^\s*\d{1,2}:\d{2}\s*(?:am|pm)\s*$", repl="", flags=0),
        RegexRule(pattern=r"(?m)^\s*\d{4}-\d{2}-\d{2}\s*$", repl="", flags=0),
        # Chinese UI strings (best-effort).
        RegexRule(pattern=r"(?m)^\s*\u5728\s*slack\s*\u4e2d\u67e5\u770b\s*$", repl="", flags=0),  # 在 Slack 中查看
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
    "confluence_jira_noise": [
        # Confluence export noise (best-effort, line-oriented).
        RegexRule(pattern=r"(?mi)^\s*powered\s+by\s+atlassian\s+confluence\s*$", repl="", flags=0),
        RegexRule(pattern=r"(?mi)^\s*view\s+in\s+confluence\s*$", repl="", flags=0),
        RegexRule(pattern=r"(?mi)^\s*created\s+by\b.*$", repl="", flags=0),
        RegexRule(pattern=r"(?mi)^\s*last\s+updated\b.*$", repl="", flags=0),
    ],
    "wechat_mp_noise": [
        # WeChat official account (公众号) export / copy-paste call-to-action lines.
        RegexRule(pattern=r"(?m)^\s*\u9605\u8bfb\u539f\u6587\s*$", repl="", flags=0),  # 阅读原文
        RegexRule(pattern=r"(?m)^\s*\u70b9\u51fb\u4e0a\u65b9.*(?:\u5173\u6ce8|\u8ba2\u9605).*$", repl="", flags=0),
        RegexRule(pattern=r"(?m)^\s*\u957f\u6309.*\u8bc6\u522b.*\u4e8c\u7ef4\u7801.*(?:\u5173\u6ce8|\u6dfb\u52a0).*$", repl="", flags=0),
        RegexRule(pattern=r"(?m)^\s*(?:\u626b\u4e00\u626b|\u626b\u63cf).*\u4e8c\u7ef4\u7801.*(?:\u5173\u6ce8|\u6dfb\u52a0).*$", repl="", flags=0),
        RegexRule(pattern=r"(?m)^\s*(?:\u5728\u770b|\u70b9\u8d5e|\u8f6c\u53d1|\u5206\u4eab(?:\u5230)?\u670b\u53cb\u5708)\s*$", repl="", flags=0),
    ],
    "pdf_header_footer_cn": [
        # Chinese page header/footer lines that include a title/company prefix.
        # Plain "第 N 页" forms are already covered by DEFAULT_MARKDOWN_RULES.
        RegexRule(
            pattern=r"(?m)^[ \t]*[\u4e00-\u9fffA-Za-z0-9（）()《》·._/\\ -]{2,80}[ \t]+第[ \t]*\d+[ \t]*页(?:[ \t]*/[ \t]*(?:\u5171[ \t]*)?\d+[ \t]*页)?[ \t]*$",
            repl="",
            flags=0,
        ),
        RegexRule(
            pattern=r"(?m)^[ \t]*[\u4e00-\u9fffA-Za-z0-9（）()《》·._/\\ -]{2,80}[ \t]+第[ \t]*\d+[ \t]*页[ \t]*$",
            repl="",
            flags=0,
        ),
        RegexRule(
            pattern=r"(?m)^[ \t]*[\u4e00-\u9fffA-Za-z0-9（）()《》·._/\\ -]{2,80}[ \t]*[|｜][ \t]*第[ \t]*\d+[ \t]*页(?:[ \t]*/[ \t]*\u5171?[ \t]*\d+[ \t]*页)?[ \t]*$",
            repl="",
            flags=0,
        ),
    ],
    "notion_export_noise": [
        # Notion markdown export noise (best-effort, line-oriented).
        RegexRule(pattern=r"(?mi)^\s*exported\s+from\s+notion\b.*$", repl="", flags=0),
        RegexRule(pattern=r"(?mi)^\s*created\s+time\b.*$", repl="", flags=0),
        RegexRule(pattern=r"(?mi)^\s*last\s+edited\s+time\b.*$", repl="", flags=0),
    ],
    "markdown_export_noise": [
        # Generic "exported/converted by ..." headers and footers.
        RegexRule(pattern=r"(?mi)^\s*generated\s+by\b.*$", repl="", flags=0),
        RegexRule(pattern=r"(?mi)^\s*exported\s+from\b.*$", repl="", flags=0),
        RegexRule(pattern=r"(?mi)^\s*created\s+with\b.*$", repl="", flags=0),
        RegexRule(pattern=r"(?mi)^\s*last\s+updated\b.*$", repl="", flags=0),
    ],
}


def list_governance_rule_packs() -> list[str]:
    return sorted(GOVERNANCE_RULE_PACKS.keys())


__all__ = [
    "GOVERNANCE_RULE_PACKS",
    "list_governance_rule_packs",
]

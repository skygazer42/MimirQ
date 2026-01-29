"""
Boilerplate removal helpers for governance cleaning.

This module targets low-value blocks such as:
- navigation / share prompts
- acknowledgements / disclaimers / copyright
- table-of-contents sections that escape line-level TOC filters

The implementation is intentionally conservative and code-fence aware.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class BoilerplateRemovalResult:
    text: str
    removed_sections: int
    removed_lines: int
    changed: bool


_CODE_FENCE_RE = re.compile(r"^\s*```")
_HEADING_RE = re.compile(r"^\s{0,3}(#{1,6})\s+(?P<title>.+?)\s*$")
_WS_RE = re.compile(r"\s+")
_PUNCT_STRIP_RE = re.compile(r"^[\s\-\u2013\u2014:：.。!！?？·•]+|[\s\-\u2013\u2014:：.。!！?？·•]+$")


def _normalize_heading(text: str) -> str:
    raw = (text or "").strip()
    if not raw:
        return ""
    normalized = _PUNCT_STRIP_RE.sub("", raw).strip().casefold()
    normalized = _WS_RE.sub(" ", normalized)
    return normalized


_SECTION_TITLES = {
    # Chinese
    "目录",
    "内容目录",
    "大纲",
    "致谢",
    "鸣谢",
    "版权声明",
    "免责声明",
    "法律声明",
    "隐私政策",
    "关于我们",
    "联系我们",
    "联系方式",
    # English
    "table of contents",
    "contents",
    "toc",
    "acknowledgements",
    "acknowledgments",
    "disclaimer",
    "copyright",
    "terms of use",
    "privacy policy",
    "about",
    "about us",
    "contact",
}

_SECTION_PREFIXES = {
    # Chinese
    "目录 ",
    "大纲 ",
    "致谢 ",
    "免责声明 ",
    "版权声明 ",
    # English
    "table of contents ",
    "contents ",
    "acknowledg",
    "terms ",
    "privacy ",
}

_BOILERPLATE_LINE_PATTERNS: tuple[re.Pattern[str], ...] = (
    # Strong legal/disclaimer lines.
    re.compile(r"(?mi)^\s*(?:copyright|all rights reserved)\b.*$"),
    re.compile(r"(?m)^\s*(?:\u7248\u6743\u6240\u6709|\u7248\u6743\u58f0\u660e).*$"),
    re.compile(r"(?m)^\s*(?:\u514d\u8d23\u58f0\u660e|\u6cd5\u5f8b\u58f0\u660e).*$"),
    re.compile(r"(?mi)^\s*(?:privacy policy|terms of use)\b.*$"),
    # Share/subscribe prompts commonly found in scraped articles.
    re.compile(r"(?m)^\s*(?:\u5173\u6ce8\u516c\u4f17\u53f7|\u626b\u7801\u5173\u6ce8|\u70b9\u51fb\u5173\u6ce8|\u5fae\u4fe1\u516c\u4f17\u53f7).*$"),
    re.compile(r"(?mi)^\s*(?:subscribe|follow us|share this)\b.*$"),
)


def remove_markdown_boilerplate(text: str) -> BoilerplateRemovalResult:
    """
    Remove boilerplate sections/lines from a Markdown-like text.

    Notes:
    - Code fences are preserved as-is.
    - Section removal triggers only on explicit headings.
    """
    original = text or ""
    if not original:
        return BoilerplateRemovalResult(text="", removed_sections=0, removed_lines=0, changed=False)

    lines = original.splitlines()
    out: list[str] = []
    in_code = False
    removed_sections = 0
    removed_lines = 0

    i = 0
    while i < len(lines):
        line = lines[i]

        if _CODE_FENCE_RE.match(line):
            in_code = not in_code
            out.append(line)
            i += 1
            continue

        if in_code:
            out.append(line)
            i += 1
            continue

        heading = _HEADING_RE.match(line)
        if heading:
            level = len(heading.group(1))
            title = _normalize_heading(heading.group("title"))
            should_remove = title in _SECTION_TITLES or any(title.startswith(p) for p in _SECTION_PREFIXES)
            if should_remove:
                removed_sections += 1
                # Skip heading line and subsequent lines until the next heading of
                # same or higher importance (<= level).
                i += 1
                while i < len(lines):
                    nxt = lines[i]
                    m2 = _HEADING_RE.match(nxt)
                    if m2 and len(m2.group(1)) <= level:
                        break
                    i += 1
                continue

        if any(p.match(line) for p in _BOILERPLATE_LINE_PATTERNS):
            removed_lines += 1
            i += 1
            continue

        out.append(line)
        i += 1

    cleaned = "\n".join(out)
    return BoilerplateRemovalResult(
        text=cleaned,
        removed_sections=removed_sections,
        removed_lines=removed_lines,
        changed=(cleaned != original),
    )


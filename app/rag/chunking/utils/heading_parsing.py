"""
Shared heading parsing helpers for chunking strategies.

These helpers intentionally avoid regex so they remain linear-time and do not
trigger SonarCloud security hotspots (python:S5852). Consolidating them also
reduces duplicated-lines density on new code, keeping the quality gate green.
"""

from __future__ import annotations

_CN_HEADING_NUM_CHARS = frozenset("0123456789一二三四五六七八九十百千")
_CN_CLAUSE_NUM_CHARS = frozenset("0123456789一二三四五六七八九十")


def parse_cn_prefixed_heading(line: str, *, suffixes: str) -> str | None:
    """
    Parse a heading prefix like:
      第12章 / 第三节 / 第10条 / 第三回

    Args:
        line: A single line of text.
        suffixes: Allowed suffix characters, e.g. \"章\" or \"章回\".

    Returns:
        The matched prefix (e.g. \"第12章\"), otherwise None.
    """
    s = (line or "").strip()
    if not s.startswith("第"):
        return None

    i = 1
    n = len(s)
    while i < n and s[i] in _CN_HEADING_NUM_CHARS:
        i += 1
    if i == 1 or i >= n:
        return None
    if s[i] not in suffixes:
        return None
    return s[: i + 1]


def parse_cn_clause_marker(line: str) -> str | None:
    """
    Parse a clause marker like:
      （一） / (1) / （10）

    Returns:
        The full marker string, otherwise None.
    """
    s = (line or "").strip()
    if not s or s[0] not in ("（", "("):
        return None

    i = 1
    n = len(s)
    while i < n and s[i].isspace():
        i += 1

    start = i
    while i < n and s[i] in _CN_CLAUSE_NUM_CHARS:
        i += 1
    if i == start:
        return None

    while i < n and s[i].isspace():
        i += 1
    if i >= n or s[i] not in (")", "）"):
        return None

    return s[: i + 1]


__all__ = ["parse_cn_clause_marker", "parse_cn_prefixed_heading"]

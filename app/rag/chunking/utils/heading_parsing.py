"""
Shared heading parsing helpers for chunking strategies.

These helpers intentionally avoid regex so they remain linear-time and do not
trigger catastrophic-backtracking hotspots. Consolidating them also
reduces duplicated-lines density on new code, keeping the quality gate green.
"""


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


def parse_markdown_hash_heading(line: str) -> tuple[int, str] | None:
    """
    Parse a Markdown ATX heading like:
      ### Title

    Returns:
        (level, title) where level is 1..6 and title is trimmed.

    Notes:
    - Allows up to 3 leading spaces (CommonMark).
    - Requires at least one whitespace after the leading # run.
    """
    raw = str(line or "")
    if not raw:
        return None

    i = 0
    # CommonMark allows up to 3 spaces of indentation before headings.
    while i < len(raw) and i < 3 and raw[i] in (" ", "\t"):
        i += 1
    s = raw[i:]
    if not s.startswith("#"):
        return None

    level = 0
    n = len(s)
    while level < n and level < 6 and s[level] == "#":
        level += 1
    if level <= 0 or level > 6:
        return None
    # Reject headings with more than 6 #'s (rare, but avoids false positives).
    if level < n and s[level] == "#":
        return None

    j = level
    if j >= n or not s[j].isspace():
        return None
    while j < n and s[j].isspace():
        j += 1
    title = s[j:].strip()
    if not title:
        return None
    return level, title


def normalize_spaces(text: str) -> str:
    """
    Collapse runs of whitespace into single spaces.

    We intentionally avoid regex to prevent catastrophic-backtracking hotspots.
    """
    return " ".join(str(text or "").split())


def normalize_spaces_lower(text: str) -> str:
    """
    Normalize text for synonym-map lookups.
    """
    return normalize_spaces(text).lower()


def strip_numbered_heading_prefix(text: str) -> str:
    """
    Strip common numbering prefixes like:
      1.2 Summary
      3) Timeline

    We intentionally avoid regex to prevent catastrophic-backtracking hotspots.
    """
    s = str(text or "").lstrip()
    if not s or not s[:1].isdigit():
        return s

    i = 0
    while i < len(s) and s[i].isdigit():
        i += 1

    groups = 0
    while groups < 3 and i < len(s) and s[i] == ".":
        j = i + 1
        if j >= len(s) or not s[j].isdigit():
            break
        while j < len(s) and s[j].isdigit():
            j += 1
        i = j
        groups += 1

    if i >= len(s):
        return s
    if not (s[i].isspace() or s[i] in ")."):
        return s

    while i < len(s) and (s[i].isspace() or s[i] in ")."):
        i += 1
    while i < len(s) and s[i].isspace():
        i += 1
    return s[i:]


__all__ = [
    "normalize_spaces",
    "normalize_spaces_lower",
    "parse_cn_clause_marker",
    "parse_cn_prefixed_heading",
    "parse_markdown_hash_heading",
    "strip_numbered_heading_prefix",
]

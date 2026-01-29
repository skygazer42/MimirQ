"""
Segmentation helpers for governance cleaning.

Chunking often treats blank lines as paragraph boundaries. This module provides
simple, code-fence-aware helpers to control the number of consecutive blank
lines kept in the final text.
"""

from __future__ import annotations

import re

_CODE_FENCE_RE = re.compile(r"^\s*```")


def limit_blank_lines(text: str, *, max_blank_lines: int) -> str:
    """
    Limit consecutive blank lines outside fenced code blocks.

    - max_blank_lines=0 removes all blank lines (merges paragraphs).
    - max_blank_lines=1 keeps at most one blank line between paragraphs (default).
    - max_blank_lines=2 keeps up to two blank lines (stronger separation).
    """
    raw = text or ""
    if not raw:
        return raw

    max_blank_lines = int(max_blank_lines or 0)
    if max_blank_lines < 0:
        max_blank_lines = 0
    if max_blank_lines > 50:
        max_blank_lines = 50

    lines = raw.split("\n")
    out: list[str] = []
    in_code = False
    blank_run = 0

    for line in lines:
        if _CODE_FENCE_RE.match(line):
            in_code = not in_code
            out.append(line)
            blank_run = 0
            continue

        if in_code:
            out.append(line)
            continue

        if not (line or "").strip():
            blank_run += 1
            if blank_run <= max_blank_lines:
                out.append("")
            continue

        blank_run = 0
        out.append(line)

    return "\n".join(out)


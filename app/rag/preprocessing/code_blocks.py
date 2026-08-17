"""
Code-block normalization helpers for governance cleaning.

Currently supported:
- Strip leading line numbers in fenced code blocks (``` ... ```), when the
  block appears to be line-numbered output from copy/paste or PDF export.

This is opt-in because it can be destructive for certain content.
"""


import re
from dataclasses import dataclass

from app.rag.core.logging import get_logger


@dataclass(frozen=True)
class CodeLineNumberStripResult:
    text: str
    blocks_changed: int
    lines_stripped: int
    changed: bool


_CODE_FENCE_RE = re.compile(r"^\s*```")
# Capture the whitespace after the line number so we can preserve indentation
# (drop the first separator space, keep remaining indent).
_LINE_NUMBER_RE = re.compile(r"^(?P<prefix>[ \t]*)(?P<num>\d{1,5})(?P<sep>[:.)]?)(?P<ws>[ \t]+)(?P<body>\S.*)$")


def _should_strip_line_numbers(code_lines: list[str]) -> bool:
    # Consider only non-empty lines.
    non_empty = [ln for ln in code_lines if (ln or "").strip()]
    if len(non_empty) < 5:
        return False

    nums: list[int] = []
    matched = 0
    for ln in non_empty:
        m = _LINE_NUMBER_RE.match(ln)
        if not m:
            continue
        matched += 1
        try:
            nums.append(int(m.group("num")))
        except Exception:
            get_logger(__name__).debug("Skipping item after non-critical exception", exc_info=True)
            continue

    if matched < max(3, int(len(non_empty) * 0.6)):
        return False

    # Heuristic: numbers should be roughly increasing by 1.
    if len(nums) <= 2:
        return True
    inc = 0
    for a, b in zip(nums, nums[1:], strict=False):
        if b == a + 1:
            inc += 1
    return (inc / max(1, len(nums) - 1)) >= 0.5


def _strip_line_numbers_from_block(code_lines: list[str]) -> tuple[list[str], int, bool]:
    out: list[str] = []
    lines_stripped = 0
    changed_any = False
    for ln in code_lines:
        m = _LINE_NUMBER_RE.match(ln or "")
        if not m:
            out.append(ln)
            continue
        ws = m.group("ws") or ""
        out.append(f"{m.group('prefix')}{ws[1:]}{m.group('body')}")
        lines_stripped += 1
        changed_any = True
    return out, lines_stripped, changed_any


def _flush_code_block(current_block: list[str]) -> tuple[list[str], int, int]:
    if not current_block:
        return [], 0, 0
    if not _should_strip_line_numbers(current_block):
        return list(current_block), 0, 0
    cleaned_block, lines_stripped, changed_any = _strip_line_numbers_from_block(current_block)
    return cleaned_block, 1 if changed_any else 0, lines_stripped


def strip_fenced_code_line_numbers(text: str) -> CodeLineNumberStripResult:
    original = text or ""
    if not original:
        return CodeLineNumberStripResult(text="", blocks_changed=0, lines_stripped=0, changed=False)

    lines = original.splitlines()
    out: list[str] = []
    in_code = False
    current_block: list[str] = []
    blocks_changed = 0
    lines_stripped = 0

    for ln in lines:
        if _CODE_FENCE_RE.match(ln):
            if in_code:
                # End of block: flush collected lines before writing fence.
                cleaned_block, block_changed, stripped_count = _flush_code_block(current_block)
                out.extend(cleaned_block)
                blocks_changed += block_changed
                lines_stripped += stripped_count
                current_block.clear()
                in_code = False
                out.append(ln)
                continue

            # Start of block: write fence and begin collecting.
            in_code = True
            out.append(ln)
            continue

        if in_code:
            current_block.append(ln)
            continue

        out.append(ln)

    # Unclosed fence: treat as normal text (best-effort).
    if current_block:
        out.extend(current_block)

    cleaned = "\n".join(out)
    return CodeLineNumberStripResult(
        text=cleaned,
        blocks_changed=blocks_changed,
        lines_stripped=lines_stripped,
        changed=(cleaned != original),
    )


__all__ = [
    "CodeLineNumberStripResult",
    "strip_fenced_code_line_numbers",
]

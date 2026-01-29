"""
Markdown table normalization helpers for governance cleaning.

This module intentionally avoids semantic rewriting. It only:
- Trims excessive whitespace around pipe-delimited cells
- Normalizes separator rows (---/:-:) formatting
- Pads/truncates rows to a consistent column count within a block

It is code-fence aware (caller can safely apply to Markdown-like text).
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class TableNormalizeResult:
    text: str
    tables: int
    rows_changed: int
    changed: bool


_CODE_FENCE_RE = re.compile(r"^\s*```")
# Allow rows without leading/trailing pipes (common Markdown style).
_TABLE_LINE_RE = re.compile(r"^(?P<prefix>[ \t]*)\|?\s*[^|]*(\|\s*[^|]*)+\|?\s*$")
_SEP_CELL_RE = re.compile(r"^\s*:?-{3,}:?\s*$")


def _split_table_row(line: str) -> tuple[str, list[str]]:
    m = _TABLE_LINE_RE.match(line)
    prefix = (m.group("prefix") if m else "") or ""
    stripped = line.strip()
    inner = stripped
    if inner.startswith("|"):
        inner = inner[1:]
    if inner.endswith("|"):
        inner = inner[:-1]
    cells = [c.strip() for c in inner.split("|")]
    return prefix, cells


def _is_separator_row(cells: list[str]) -> bool:
    if not cells:
        return False
    ok = 0
    for cell in cells:
        if _SEP_CELL_RE.match(cell or ""):
            ok += 1
    # Require that most cells look like separator definitions.
    return ok >= max(1, int(len(cells) * 0.8))


def _normalize_separator_cell(cell: str) -> str:
    raw = (cell or "").strip()
    if not raw:
        return "---"
    # Preserve left/right alignment colons if present.
    left = ":" if raw.startswith(":") else ""
    right = ":" if raw.endswith(":") else ""
    return f"{left}---{right}"


def normalize_markdown_tables(text: str) -> TableNormalizeResult:
    original = text or ""
    if not original:
        return TableNormalizeResult(text="", tables=0, rows_changed=0, changed=False)

    lines = original.splitlines()
    out: list[str] = []
    in_code = False
    i = 0
    tables = 0
    rows_changed = 0

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

        if not _TABLE_LINE_RE.match(line):
            out.append(line)
            i += 1
            continue

        # Collect a contiguous table block.
        block_lines: list[str] = []
        j = i
        while j < len(lines):
            ln = lines[j]
            if _CODE_FENCE_RE.match(ln):
                break
            if not _TABLE_LINE_RE.match(ln):
                break
            block_lines.append(ln)
            j += 1

        parsed_rows: list[tuple[str, list[str], bool]] = []
        max_cols = 0
        for raw in block_lines:
            prefix, cells = _split_table_row(raw)
            is_sep = _is_separator_row(cells)
            parsed_rows.append((prefix, cells, is_sep))
            max_cols = max(max_cols, len(cells))

        # Normalize rows.
        for (prefix, cells, is_sep), raw in zip(parsed_rows, block_lines, strict=False):
            padded = list(cells) + [""] * max(0, max_cols - len(cells))
            padded = padded[:max_cols] if max_cols > 0 else padded
            if is_sep:
                norm_cells = [_normalize_separator_cell(c) for c in padded]
            else:
                # Cell whitespace is normalized conservatively: collapse runs of spaces/tabs.
                norm_cells = [re.sub(r"[ \t]{2,}", " ", c.strip()) for c in padded]
            rebuilt = f"{prefix}| " + " | ".join(norm_cells) + " |"
            if rebuilt != raw:
                rows_changed += 1
            out.append(rebuilt)

        tables += 1
        i = j

    cleaned = "\n".join(out)
    return TableNormalizeResult(
        text=cleaned,
        tables=tables,
        rows_changed=rows_changed,
        changed=(cleaned != original),
    )


__all__ = [
    "TableNormalizeResult",
    "normalize_markdown_tables",
]

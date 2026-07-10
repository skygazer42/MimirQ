"""
Markdown table normalization helpers for governance cleaning.

This module intentionally avoids semantic rewriting. It only:
- Trims excessive whitespace around pipe-delimited cells
- Normalizes separator rows (---/:-:) formatting
- Pads/truncates rows to a consistent column count within a block

It is code-fence aware (caller can safely apply to Markdown-like text).
"""


import re
from dataclasses import dataclass


@dataclass(frozen=True)
class TableNormalizeResult:
    text: str
    tables: int
    rows_changed: int
    changed: bool


_CODE_FENCE_RE = re.compile(r"^\s*```")
_SEP_CELL_RE = re.compile(r"^\s*:?-{3,}:?\s*$")


def _try_parse_table_row(line: str) -> tuple[str, list[str]] | None:
    """
    Best-effort Markdown table-row parser.

    We avoid regex here to keep runtime linear-time and to prevent ReDoS-style
    security hotspots (python:S5852).
    """
    raw = str(line or "")
    if not raw or "|" not in raw:
        return None

    # Preserve leading indentation.
    i = 0
    while i < len(raw) and raw[i] in (" ", "\t"):
        i += 1
    prefix = raw[:i]

    stripped = raw.strip()
    if not stripped:
        return None

    inner = stripped
    if inner.startswith("|"):
        inner = inner[1:]
    if inner.endswith("|"):
        inner = inner[:-1]

    # Require at least 2 cells.
    if "|" not in inner:
        return None
    cells = [c.strip() for c in inner.split("|")]
    if len(cells) < 2:
        return None
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

        parsed = _try_parse_table_row(line)
        if parsed is None:
            out.append(line)
            i += 1
            continue

        # Collect a contiguous table block.
        block_lines: list[str] = []
        block_parsed: list[tuple[str, list[str]]] = []
        j = i
        while j < len(lines):
            ln = lines[j]
            if _CODE_FENCE_RE.match(ln):
                break
            row = _try_parse_table_row(ln)
            if row is None:
                break
            block_lines.append(ln)
            block_parsed.append(row)
            j += 1

        parsed_rows: list[tuple[str, list[str], bool]] = []
        max_cols = 0
        for prefix, cells in block_parsed:
            is_sep = _is_separator_row(cells)
            parsed_rows.append((prefix, cells, is_sep))
            max_cols = max(max_cols, len(cells))

        # Only normalize when the block resembles a real Markdown table
        # (header + separator row). Otherwise we risk rewriting text that happens
        # to contain pipes (e.g. "a | b").
        if len(parsed_rows) < 2 or not any(is_sep for _p, _c, is_sep in parsed_rows):
            out.extend(block_lines)
            i = j
            continue

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

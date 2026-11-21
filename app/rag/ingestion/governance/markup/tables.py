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


def parse_markdown_table_row(line: str, *, min_columns: int = 2) -> tuple[str, list[str]] | None:
    """
    Best-effort Markdown table-row parser.

    We avoid regex here to keep runtime linear-time and to prevent ReDoS-style
    security hotspots (python:S5852).
    """
    raw = line
    if "|" not in raw:
        return None

    prefix = raw[: len(raw) - len(raw.lstrip(" \t"))]
    stripped = raw.strip()
    cells: list[str] = []
    current: list[str] = []
    escaped = False
    last_delimiter = -1
    for index, character in enumerate(stripped):
        if character == "|" and not escaped:
            cells.append("".join(current).strip())
            current.clear()
            last_delimiter = index
        else:
            current.append(character)
        escaped = character == "\\" and not escaped
    cells.append("".join(current).strip())
    if stripped.startswith("|"):
        cells = cells[1:]
    if last_delimiter == len(stripped) - 1:
        cells.pop()
    if len(cells) < min_columns:
        return None
    return prefix, cells


def is_markdown_table_separator(cells: list[str]) -> bool:
    return bool(cells) and all(_SEP_CELL_RE.fullmatch(cell) for cell in cells)


def _normalize_separator_cell(cell: str) -> str:
    raw = cell.strip()
    # Preserve left/right alignment colons if present.
    left = ":" if raw.startswith(":") else ""
    right = ":" if raw.endswith(":") else ""
    return f"{left}---{right}"


def _collect_table_block(
    lines: list[str], start_idx: int, first_row: tuple[str, list[str]]
) -> tuple[list[tuple[str, list[str]]], int]:
    block_parsed = [first_row]
    end_idx = start_idx + 1
    while end_idx < len(lines):
        line = lines[end_idx]
        if _CODE_FENCE_RE.match(line):
            break
        row = parse_markdown_table_row(line)
        if row is None:
            break
        block_parsed.append(row)
        end_idx += 1
    return block_parsed, end_idx


def _normalize_table_rows(
    parsed_rows: list[tuple[str, list[str], bool]],
    block_lines: list[str],
    *,
    max_cols: int,
) -> tuple[list[str], int]:
    normalized_rows: list[str] = []
    rows_changed = 0
    for (prefix, cells, is_separator), raw in zip(parsed_rows, block_lines, strict=True):
        padded = cells + [""] * (max_cols - len(cells))
        if is_separator:
            norm_cells = [_normalize_separator_cell(cell) for cell in padded]
        else:
            norm_cells = [re.sub(r"[ \t]{2,}", " ", cell.strip()) for cell in padded]
        rebuilt = f"{prefix}| " + " | ".join(norm_cells) + " |"
        rows_changed += int(rebuilt != raw)
        normalized_rows.append(rebuilt)
    return normalized_rows, rows_changed


def normalize_markdown_tables(text: str) -> TableNormalizeResult:
    original = text
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

        parsed = parse_markdown_table_row(line)
        if parsed is None:
            out.append(line)
            i += 1
            continue

        block_parsed, j = _collect_table_block(lines, i, parsed)
        block_lines = lines[i:j]
        parsed_rows = [(prefix, cells, is_markdown_table_separator(cells)) for prefix, cells in block_parsed]

        # Only normalize when the block resembles a real Markdown table
        # (header + separator row). Otherwise we risk rewriting text that happens
        # to contain pipes (e.g. "a | b").
        if len(parsed_rows) < 2 or not any(is_sep for _p, _c, is_sep in parsed_rows):
            out.extend(block_lines)
            i = j
            continue

        max_cols = max(len(cells) for _prefix, cells in block_parsed)
        normalized_rows, changed_count = _normalize_table_rows(parsed_rows, block_lines, max_cols=max_cols)
        out.extend(normalized_rows)
        rows_changed += changed_count

        tables += 1
        i = j

    cleaned = "\n".join(out) if rows_changed else original
    return TableNormalizeResult(
        text=cleaned,
        tables=tables,
        rows_changed=rows_changed,
        changed=(cleaned != original),
    )


__all__ = [
    "TableNormalizeResult",
    "parse_markdown_table_row",
    "is_markdown_table_separator",
    "normalize_markdown_tables",
]

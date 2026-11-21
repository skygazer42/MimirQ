import re
from dataclasses import dataclass
from typing import Any

from app.rag.ingestion.parsing.enrich.table_cell_schema import TableCell, TableExtraction

_MD_TABLE_SEP_CELL_RE = re.compile(r"^\s*:?-{3,}:?\s*$")


@dataclass(frozen=True, slots=True)
class MarkdownTableProfile:
    columns: list[str]
    row_count: int
    column_count: int

    def to_metadata(self) -> dict[str, Any]:
        return {
            "table_columns": list(self.columns),
            "table_shape": {"rows": int(self.row_count), "columns": int(self.column_count)},
        }


def _split_markdown_row(line: str) -> list[str]:
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|") and (len(s[:-1]) - len(s[:-1].rstrip("\\"))) % 2 == 0:
        s = s[:-1]
    cells: list[str] = []
    start = 0
    backslashes = 0
    for index, char in enumerate(s):
        if char == "|" and backslashes % 2 == 0:
            cells.append(s[start:index].replace(r"\|", "|").strip())
            start = index + 1
        backslashes = backslashes + 1 if char == "\\" else 0
    cells.append(s[start:].replace(r"\|", "|").strip())
    return cells


def profile_markdown_table(text: str) -> MarkdownTableProfile | None:
    lines = [line.strip() for line in text.splitlines() if line.strip().startswith("|")]
    if len(lines) < 2:
        return None

    header = _split_markdown_row(lines[0])
    if not any(header):
        return None
    sep = _split_markdown_row(lines[1])
    if not sep or len(sep) != len(header) or not all(_MD_TABLE_SEP_CELL_RE.match(cell) for cell in sep):
        return None

    row_count = len(lines[2:])
    return MarkdownTableProfile(columns=header, row_count=row_count, column_count=len(header))


def extract_markdown_table(
    text: str,
    *,
    page: int | None = None,
    bbox: dict[str, Any] | None = None,
    source_element_id: str | None = None,
) -> TableExtraction | None:
    lines = [line.strip() for line in text.splitlines() if line.strip().startswith("|")]
    if len(lines) < 2:
        return None
    header = _split_markdown_row(lines[0])
    sep = _split_markdown_row(lines[1])
    if not header or len(sep) != len(header) or not all(_MD_TABLE_SEP_CELL_RE.match(cell) for cell in sep):
        return None

    rows: list[list[str]] = []
    for line in lines[2:]:
        row = _split_markdown_row(line)
        if len(row) > len(header):
            return None
        rows.append(row + [""] * (len(header) - len(row)))

    cells: list[TableCell] = []
    for col_index, col in enumerate(header):
        cells.append(TableCell(row_index=0, col_index=col_index, text=col, is_header=True))
    for row_index, row in enumerate(rows, start=1):
        for col_index, cell in enumerate(row):
            cells.append(TableCell(row_index=row_index, col_index=col_index, text=cell, is_header=False))

    return TableExtraction(
        columns=header,
        rows=rows,
        cells=cells,
        page=page,
        bbox=bbox,
        source_element_id=source_element_id,
        header_rows=1,
        metadata={"source": "markdown_table"},
    )


__all__ = ["MarkdownTableProfile", "extract_markdown_table", "profile_markdown_table"]

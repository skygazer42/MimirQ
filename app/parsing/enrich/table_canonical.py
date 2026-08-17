import re
from dataclasses import dataclass
from typing import Any

from app.parsing.enrich.table_cell_schema import TableCell, TableExtraction

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
    s = str(line or "").strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [part.replace(r"\|", "|").strip() for part in s.split("|")]


def profile_markdown_table(text: str) -> MarkdownTableProfile | None:
    lines = [
        str(line or "").strip() for line in str(text or "").splitlines() if str(line or "").strip().startswith("|")
    ]
    if len(lines) < 2:
        return None

    header = _split_markdown_row(lines[0])
    if not any(header):
        return None
    sep = _split_markdown_row(lines[1])
    if not sep or len(sep) != len(header) or not all(_MD_TABLE_SEP_CELL_RE.match(cell or "") for cell in sep):
        return None

    row_count = 0
    for line in lines[2:]:
        row = _split_markdown_row(line)
        if any(row):
            row_count += 1
    return MarkdownTableProfile(columns=[str(col) for col in header], row_count=row_count, column_count=len(header))


def extract_markdown_table(
    text: str,
    *,
    page: int | None = None,
    bbox: dict[str, Any] | None = None,
    source_element_id: str | None = None,
) -> TableExtraction | None:
    lines = [
        str(line or "").strip() for line in str(text or "").splitlines() if str(line or "").strip().startswith("|")
    ]
    if len(lines) < 2:
        return None
    header = _split_markdown_row(lines[0])
    sep = _split_markdown_row(lines[1])
    if not header or len(sep) != len(header) or not all(_MD_TABLE_SEP_CELL_RE.match(cell or "") for cell in sep):
        return None

    rows: list[list[str]] = []
    for line in lines[2:]:
        row = _split_markdown_row(line)
        if any(row):
            rows.append(row[: len(header)] + [""] * max(0, len(header) - len(row)))

    cells: list[TableCell] = []
    for col_index, col in enumerate(header):
        cells.append(TableCell(row_index=0, col_index=col_index, text=str(col), is_header=True))
    for row_index, row in enumerate(rows, start=1):
        for col_index, cell in enumerate(row[: len(header)]):
            cells.append(TableCell(row_index=row_index, col_index=col_index, text=str(cell), is_header=False))

    return TableExtraction(
        columns=[str(col) for col in header],
        rows=rows,
        cells=cells,
        page=page,
        bbox=bbox,
        source_element_id=source_element_id,
        header_rows=1,
        metadata={"source": "markdown_table"},
    )


__all__ = ["MarkdownTableProfile", "extract_markdown_table", "profile_markdown_table"]

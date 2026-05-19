from __future__ import annotations

import csv
import html
from io import StringIO

from app.parsing.enrich.table_cell_schema import TableExtraction


def _escape_markdown_cell(value: str) -> str:
    return str(value or "").replace("|", r"\|").strip()


def render_table_markdown(table: TableExtraction) -> str:
    columns = [_escape_markdown_cell(col) for col in table.columns]
    lines = [
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join("---" for _ in columns) + " |",
    ]
    for row in table.rows:
        padded = list(row[: len(columns)]) + [""] * max(0, len(columns) - len(row))
        lines.append("| " + " | ".join(_escape_markdown_cell(cell) for cell in padded) + " |")
    return "\n".join(lines)


def render_table_csv(table: TableExtraction) -> str:
    buffer = StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(list(table.columns))
    writer.writerows([list(row) for row in table.rows])
    return buffer.getvalue().rstrip("\n")


def render_table_html(table: TableExtraction) -> str:
    header = "".join(f"<th>{html.escape(str(col or ''))}</th>" for col in table.columns)
    rows = []
    for row in table.rows:
        padded = list(row[: table.col_count]) + [""] * max(0, table.col_count - len(row))
        rows.append("<tr>" + "".join(f"<td>{html.escape(str(cell or ''))}</td>" for cell in padded) + "</tr>")
    return "<table><thead><tr>" + header + "</tr></thead><tbody>" + "".join(rows) + "</tbody></table>"


__all__ = ["render_table_csv", "render_table_html", "render_table_markdown"]

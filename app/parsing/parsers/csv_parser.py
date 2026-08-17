"""
CSV parser (fallback / lightweight).

MarkItDown can convert CSV into Markdown, but a lightweight fallback is useful
when MarkItDown is unavailable or fails. We preserve CSV structure as
key-value rows, which works well for downstream chunking and retrieval.
"""


import csv
import io
from pathlib import Path

from langchain_core.documents import Document

from app.parsing.utils.text import read_text_file


def _safe_cell(value: str, *, max_chars: int = 2000) -> str:
    text = (value or "").replace("\r", " ").replace("\n", " ").strip()
    if max_chars > 0 and len(text) > max_chars:
        return text[: max_chars - 1] + "…"
    return text


def _sniff_csv_format(sample: str) -> tuple[csv.Dialect, str, bool]:
    delimiter = ","
    dialect: csv.Dialect = csv.excel
    try:
        sniffed = csv.Sniffer().sniff(sample, delimiters=",\t;|")
        dialect = sniffed
        delimiter = getattr(sniffed, "delimiter", ",") or ","
    except Exception:
        dialect = csv.excel
        delimiter = ","

    has_header = False
    try:
        has_header = csv.Sniffer().has_header(sample)
    except Exception:
        has_header = False

    return dialect, delimiter, has_header


def _read_csv_rows(
    *,
    raw: str,
    dialect: csv.Dialect,
    has_header: bool,
    max_rows: int | None,
) -> tuple[list[str], list[list[str]]]:
    reader = csv.reader(io.StringIO(raw), dialect)
    first = next(reader, None)
    if first is None:
        return [], []

    header = [c.strip() or f"col{i+1}" for i, c in enumerate(first)]
    rows: list[list[str]] = []
    if not has_header:
        rows.append(first)

    for row in reader:
        if row is None:
            continue
        rows.append(row)
        if max_rows is not None and len(rows) >= max_rows:
            break

    return header, rows


def _render_csv_content(
    *,
    file_name: str,
    delimiter: str,
    header: list[str],
    rows: list[list[str]],
    max_cell_chars: int,
) -> str:
    if not header:
        return ""

    out = io.StringIO()
    out.write(f"CSV: {file_name}\n")
    out.write(f"Delimiter: {delimiter!r}\n")
    out.write(f"Columns: {', '.join(header)}\n\n")

    for idx, row in enumerate(rows, start=1):
        pairs = []
        for j, val in enumerate(row):
            key = header[j] if j < len(header) else f"col{j+1}"
            pairs.append(f"{key}={_safe_cell(val, max_chars=max_cell_chars)}")
        out.write(f"row {idx}: " + " | ".join(pairs) + "\n")

    return out.getvalue()


class CsvParser:
    """CSV parser that emits a row-oriented, chunk-friendly text representation."""

    def __init__(self, *, max_rows: int | None = None, max_cell_chars: int = 2000) -> None:
        self.max_rows = int(max_rows) if max_rows is not None else None
        self.max_cell_chars = int(max_cell_chars or 0)

    def parse(self, file_path: Path) -> list[Document]:
        decoded = read_text_file(file_path)
        raw = decoded.text or ""
        sample = raw[:8192]
        dialect, delimiter, has_header = _sniff_csv_format(sample)
        header, rows = _read_csv_rows(
            raw=raw,
            dialect=dialect,
            has_header=has_header,
            max_rows=self.max_rows,
        )
        row_count = len(rows)
        content = _render_csv_content(
            file_name=file_path.name,
            delimiter=delimiter,
            header=header,
            rows=rows,
            max_cell_chars=self.max_cell_chars,
        )

        metadata = {
            "source": str(file_path.name),
            "file_type": "csv",
            "csv_delimiter": delimiter,
            "csv_has_header": bool(has_header),
            "csv_rows_emitted": int(row_count),
            "encoding": decoded.encoding,
            "encoding_confidence": decoded.confidence,
            "encoding_had_bom": decoded.had_bom,
        }
        if header:
            metadata["csv_columns"] = header

        return [Document(page_content=content, metadata=metadata)]

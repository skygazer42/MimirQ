#
#  Copyright 2025 The InfiniFlow Authors. All Rights Reserved.
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
#

"""
Excel parser (fallback / lightweight).

Used as a best-effort fallback when MarkItDown is unavailable or fails.
Supports .xlsx via openpyxl; .xls uses pandas engines and may fail.

Outputs Markdown tables (best-effort) for better fidelity in downstream preview/RAG.
"""

import io
import logging
from contextlib import ExitStack, contextmanager
from html import escape
from pathlib import Path
from typing import Any

from langchain_core.documents import Document

logger = logging.getLogger(__name__)

_EMPTY_SHEET_MARKDOWN = "_Empty sheet._\n\n"


@contextmanager
def _owned_workbook(workbook: Any):
    pending_error: BaseException | None = None
    try:
        yield workbook
    except BaseException as exc:
        pending_error = exc
        raise
    finally:
        try:
            workbook.close()
        except BaseException as exc:
            if pending_error is None:
                raise
            pending_error.add_note(f"Excel workbook cleanup failed: {type(exc).__name__}")
            logger.warning("Excel workbook cleanup failed while propagating an error", exc_info=True)


def _safe_cell(value: object, *, max_chars: int) -> str:
    text = "" if value is None else str(value)
    text = text.replace("\r", " ").replace("\n", " ").strip()
    if max_chars > 0 and len(text) > max_chars:
        return text[: max_chars - 1] + "…"
    return text


def _escape_md_cell(text: str) -> str:
    text = (text).replace("\r", " ").replace("\n", " ").strip()
    text = " ".join(text.split())
    # Keep Markdown tables stable.
    return text.replace("|", r"\|")


def _md_table(rows: list[list[str]]) -> str:
    if not rows:
        return ""
    width = max(len(r) for r in rows)
    norm = [r + [""] * (width - len(r)) for r in rows]
    header = norm[0]
    body = norm[1:]
    out: list[str] = []
    out.append("| " + " | ".join(header) + " |")
    out.append("| " + " | ".join(["---"] * width) + " |")
    for r in body:
        out.append("| " + " | ".join(r) + " |")
    return "\n".join(out).strip()


def _build_cell_grid(ws: Any, *, max_rows: int, max_cols: int) -> list[list[object]]:
    grid: list[list[object]] = [[None for _ in range(max_cols)] for _ in range(max_rows)]
    for r in range(1, max_rows + 1):
        for c in range(1, max_cols + 1):
            grid[r - 1][c - 1] = ws.cell(row=r, column=c).value
    return grid


def _merged_ranges(ws: Any) -> list[object]:
    return list(ws.merged_cells.ranges)


def _fill_merged_ranges(ws: Any, *, grid: list[list[object]], max_rows: int, max_cols: int) -> None:
    for merged in _merged_ranges(ws):
        min_col, min_row, max_col, max_row = merged.bounds
        if min_row > max_rows or min_col > max_cols:
            continue
        top_left = ws.cell(row=min_row, column=min_col).value
        for r in range(min_row, min(max_row, max_rows) + 1):
            for c in range(min_col, min(max_col, max_cols) + 1):
                grid[r - 1][c - 1] = top_left


def _row_has_data(row: list[object]) -> bool:
    return any(str(v).strip() for v in row if v is not None)


def _trim_grid(grid: list[list[object]], *, max_cols: int) -> list[list[object]]:
    last_row = 0
    for index, row in enumerate(grid, start=1):
        if _row_has_data(row):
            last_row = index
    if last_row <= 0:
        return []
    trimmed = grid[:last_row]

    last_col = 0
    for col_index in range(1, max_cols + 1):
        if any(row[col_index - 1] is not None and str(row[col_index - 1]).strip() for row in trimmed):
            last_col = col_index
    if last_col <= 0:
        return []
    return [row[:last_col] for row in trimmed]


class ExcelParser:
    """Parse Excel into a row-oriented, chunk-friendly text representation."""

    def __init__(
        self,
        *,
        max_sheets: int = 0,
        max_rows: int = 0,
        max_cols: int = 0,
        max_cell_chars: int = 2000,
    ) -> None:
        if min(max_sheets, max_rows, max_cols, max_cell_chars) < 0:
            raise ValueError("Excel limits must be nonnegative (zero means unlimited)")
        self.max_sheets = max_sheets
        self.max_rows = max_rows
        self.max_cols = max_cols
        self.max_cell_chars = max_cell_chars

    def parse(self, file_path: Path) -> list[Document]:
        ext = file_path.suffix.lower()

        if ext == ".xlsx":
            return self._parse_xlsx(file_path)

        # Best-effort for .xls using pandas; may require extra engines.
        return self._parse_via_pandas(file_path)

    def _sheet_limits(self, ws: Any) -> tuple[int, int]:
        max_rows = min(self.max_rows, ws.max_row) if self.max_rows > 0 else ws.max_row
        max_cols = min(self.max_cols, ws.max_column) if self.max_cols > 0 else ws.max_column
        return max(0, max_rows), max(0, max_cols)

    def _markdown_rows(self, grid: list[list[object]]) -> list[list[str]]:
        rows_md: list[list[str]] = []
        for row in grid:
            cells = [_escape_md_cell(_safe_cell(value, max_chars=self.max_cell_chars)) for value in row]
            rows_md.append(cells)
        return rows_md

    def _sheet_markdown(self, ws: Any) -> tuple[str, int, bool]:
        max_rows, max_cols = self._sheet_limits(ws)
        if max_rows <= 0 or max_cols <= 0:
            return _EMPTY_SHEET_MARKDOWN, 0, False

        grid = _build_cell_grid(ws, max_rows=max_rows, max_cols=max_cols)
        _fill_merged_ranges(ws, grid=grid, max_rows=max_rows, max_cols=max_cols)
        grid = _trim_grid(grid, max_cols=max_cols)
        if not grid:
            return _EMPTY_SHEET_MARKDOWN, 0, False

        rows_md = self._markdown_rows(grid)
        if not rows_md:
            return _EMPTY_SHEET_MARKDOWN, 0, False

        truncated = (self.max_rows > 0 and ws.max_row > self.max_rows) or (
            self.max_cols > 0 and ws.max_column > self.max_cols
        )
        return _md_table(rows_md) + "\n\n", len(rows_md), truncated

    def _parse_xlsx(self, file_path: Path) -> list[Document]:
        # read_only=False so we can inspect merged cells reliably.
        with _owned_workbook(self._load_workbook(str(file_path), convert_tabular=False)) as wb:
            sheet_names = list(wb.sheetnames)
            limited = sheet_names[: self.max_sheets] if self.max_sheets > 0 else sheet_names

            out = io.StringIO()
            out.write(f"Excel: {file_path.name}\n")
            out.write(f"Sheets: {', '.join(limited) if limited else '(none)'}\n\n")

            emitted_rows = 0
            truncated_any = len(limited) < len(sheet_names)
            for sheet_name in limited:
                ws = wb[sheet_name]
                out.write(f"## Sheet: {sheet_name}\n\n")
                sheet_markdown, sheet_rows, sheet_truncated = self._sheet_markdown(ws)
                out.write(sheet_markdown)
                emitted_rows += sheet_rows
                truncated_any = truncated_any or sheet_truncated

            metadata = {
                "source": str(file_path.name),
                "file_type": "xlsx",
                "excel_sheets": limited,
                "excel_rows_emitted": emitted_rows,
            }
            if truncated_any:
                metadata["excel_truncated"] = True
            return [Document(page_content=out.getvalue(), metadata=metadata)]

    def _parse_via_pandas(self, file_path: Path) -> list[Document]:
        import pandas as pd  # type: ignore

        # Read a small preview; pandas will select an engine based on extension.
        try:
            df = pd.read_excel(str(file_path), nrows=self.max_rows if self.max_rows > 0 else None)
        except Exception as exc:
            raise RuntimeError(f"Excel preview failed: {exc}") from exc

        # Limit columns.
        if self.max_cols > 0 and df.shape[1] > self.max_cols:
            df = df.iloc[:, : self.max_cols]

        # Render as a Markdown table (best-effort), similar to the .xlsx path.
        cols = [str(c) for c in df.columns]

        rows_md: list[list[str]] = []
        if cols:
            rows_md.append([_escape_md_cell(_safe_cell(c, max_chars=self.max_cell_chars)) for c in cols])
        for row in df.itertuples(index=False, name=None):
            values = [_escape_md_cell(_safe_cell(v, max_chars=self.max_cell_chars)) for v in row]
            if any(values):
                rows_md.append(values)

        out = io.StringIO()
        out.write(f"Excel: {file_path.name}\n\n")
        if rows_md:
            out.write(_md_table(rows_md))
            out.write("\n")
        else:
            out.write("_Empty sheet._\n")

        metadata = {
            "source": str(file_path.name),
            "file_type": file_path.suffix.lstrip("."),
            "excel_rows_emitted": df.shape[0],
        }
        if cols:
            metadata["excel_columns"] = cols[:200]
        return [Document(page_content=out.getvalue(), metadata=metadata)]

    @staticmethod
    def _load_workbook(file_like_object, *, convert_tabular: bool = True):
        from io import BytesIO

        from openpyxl import load_workbook

        if not convert_tabular:
            return load_workbook(filename=file_like_object, read_only=False, data_only=True)

        with ExitStack() as source_owner:
            if isinstance(file_like_object, str):
                file_like_object = source_owner.enter_context(open(file_like_object, "rb"))
            elif isinstance(file_like_object, bytes):
                file_like_object = source_owner.enter_context(BytesIO(file_like_object))
            file_like_object.seek(0)
            file_head = file_like_object.read(4)
            file_like_object.seek(0)

            if not file_head.startswith((b"PK\x03\x04", b"\xd0\xcf\x11\xe0")):
                import pandas as pd

                try:
                    df = pd.read_csv(file_like_object)
                    return ExcelParser._dataframe_to_workbook(df)
                except Exception as exc:
                    raise RuntimeError(f"Failed to parse CSV as an Excel workbook: {exc}") from exc

            try:
                return load_workbook(file_like_object, data_only=True)
            except Exception as exc:
                import pandas as pd

                logger.info("openpyxl load failed; using pandas: %s", exc)
                try:
                    file_like_object.seek(0)
                    df = pd.read_excel(file_like_object)
                    return ExcelParser._dataframe_to_workbook(df)
                except Exception as pandas_exc:
                    raise RuntimeError(f"pandas.read_excel failed after openpyxl: {exc}") from pandas_exc

    @staticmethod
    def _dataframe_to_workbook(df):
        from openpyxl import Workbook

        wb = Workbook()
        try:
            ws = wb.active
            ws.title = "Data"
            for col_num, column_name in enumerate(df.columns, 1):
                ws.cell(row=1, column=col_num, value=column_name)
            for row_num, row in enumerate(df.values, 2):
                for col_num, value in enumerate(row, 1):
                    ws.cell(row=row_num, column=col_num, value=value)
            return wb
        except BaseException:
            with _owned_workbook(wb):
                raise

    def parse_html_tables(self, fnm, chunk_rows: int = 256) -> list[str]:
        if chunk_rows <= 0:
            raise ValueError("Excel chunk_rows must be positive")
        with _owned_workbook(self._load_workbook(fnm)) as wb:
            tb_chunks = []
            for sheetname in wb.sheetnames:
                rows = list(wb[sheetname].rows)
                if not rows:
                    continue
                header = (
                    "<tr>"
                    + "".join(f"<th>{escape(_safe_cell(cell.value, max_chars=0))}</th>" for cell in rows[0])
                    + "</tr>"
                )
                for start in range(0, max(1, len(rows) - 1), chunk_rows):
                    body = []
                    for row in rows[start + 1 : start + 1 + chunk_rows]:
                        cells = "".join(f"<td>{escape(_safe_cell(cell.value, max_chars=0))}</td>" for cell in row)
                        body.append(f"<tr>{cells}</tr>")
                    tb_chunks.append(f"<table><caption>{escape(sheetname)}</caption>{header}{''.join(body)}</table>\n")
            return tb_chunks

    def parse_rows(self, fnm) -> list[str]:
        with _owned_workbook(self._load_workbook(fnm)) as wb:
            res = []
            for sheetname in wb.sheetnames:
                rows = list(wb[sheetname].rows)
                if not rows:
                    continue
                header = list(rows[0])
                for row in rows[1:]:
                    fields = []
                    for index, cell in enumerate(row):
                        if cell.value is None or cell.value == "":
                            continue
                        name = _safe_cell(header[index].value, max_chars=0) if index < len(header) else ""
                        fields.append((name + "：" if name else "") + str(cell.value))
                    line = "; ".join(fields)
                    if "sheet" not in sheetname.lower():
                        line += " ——" + sheetname
                    res.append(line)
            return res

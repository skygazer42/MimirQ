"""
Excel parser (fallback / lightweight).

Used as a best-effort fallback when MarkItDown is unavailable or fails.
Supports .xlsx via openpyxl; .xls requires optional engines and may fail.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import List, Optional

from langchain_core.documents import Document


def _safe_cell(value: object, *, max_chars: int) -> str:
    text = "" if value is None else str(value)
    text = text.replace("\r", " ").replace("\n", " ").strip()
    if max_chars > 0 and len(text) > max_chars:
        return text[: max_chars - 1] + "…"
    return text


class ExcelParser:
    """Parse Excel into a row-oriented, chunk-friendly text representation."""

    def __init__(
        self,
        *,
        max_sheets: int = 3,
        max_rows: int = 50,
        max_cols: int = 20,
        max_cell_chars: int = 2000,
    ) -> None:
        self.max_sheets = int(max_sheets or 0)
        self.max_rows = int(max_rows or 0)
        self.max_cols = int(max_cols or 0)
        self.max_cell_chars = int(max_cell_chars or 0)

    def parse(self, file_path: Path) -> List[Document]:
        ext = file_path.suffix.lower()

        if ext == ".xlsx":
            return self._parse_xlsx(file_path)

        # Best-effort for .xls using pandas; may require extra engines.
        return self._parse_via_pandas(file_path)

    def _parse_xlsx(self, file_path: Path) -> List[Document]:
        try:
            from openpyxl import load_workbook  # type: ignore
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("openpyxl is not installed; cannot parse .xlsx") from exc

        wb = load_workbook(filename=str(file_path), read_only=True, data_only=True)
        sheet_names = list(getattr(wb, "sheetnames", []) or [])
        limited = sheet_names[: self.max_sheets] if self.max_sheets > 0 else sheet_names

        out = io.StringIO()
        out.write(f"Excel: {file_path.name}\n")
        out.write(f"Sheets: {', '.join(limited) if limited else '(none)'}\n\n")

        emitted_rows = 0
        for sheet_name in limited:
            ws = wb[sheet_name]
            out.write(f"[Sheet] {sheet_name}\n")
            row_idx = 0
            for row in ws.iter_rows(
                min_row=1,
                max_row=self.max_rows if self.max_rows > 0 else None,
                max_col=self.max_cols if self.max_cols > 0 else None,
                values_only=True,
            ):
                row_idx += 1
                cells = [_safe_cell(v, max_chars=self.max_cell_chars) for v in (row or ())]
                if not any(cells):
                    continue
                emitted_rows += 1
                out.write(f"row {row_idx}: " + " | ".join(cells) + "\n")
            out.write("\n")

        metadata = {
            "source": str(file_path.name),
            "file_type": "xlsx",
            "excel_sheets": limited,
            "excel_rows_emitted": int(emitted_rows),
        }
        return [Document(page_content=out.getvalue(), metadata=metadata)]

    def _parse_via_pandas(self, file_path: Path) -> List[Document]:
        try:
            import pandas as pd  # type: ignore
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("pandas is not installed; cannot parse Excel") from exc

        # Read a small preview; pandas will select an engine based on extension.
        try:
            df = pd.read_excel(str(file_path), nrows=self.max_rows if self.max_rows > 0 else None)
        except Exception as exc:
            raise RuntimeError(f"Excel preview failed: {exc}") from exc

        # Limit columns.
        if self.max_cols > 0 and getattr(df, "shape", (0, 0))[1] > self.max_cols:
            df = df.iloc[:, : self.max_cols]

        out = io.StringIO()
        out.write(f"Excel: {file_path.name}\n\n")
        out.write(df.to_string(index=False))
        out.write("\n")

        cols: Optional[list[str]] = None
        try:
            cols = [str(c) for c in list(df.columns)]
        except Exception:
            cols = None

        metadata = {
            "source": str(file_path.name),
            "file_type": file_path.suffix.lstrip("."),
            "excel_rows_emitted": int(getattr(df, "shape", (0, 0))[0]),
        }
        if cols:
            metadata["excel_columns"] = cols[:200]
        return [Document(page_content=out.getvalue(), metadata=metadata)]


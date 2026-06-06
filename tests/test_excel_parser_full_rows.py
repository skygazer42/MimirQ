from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook

from app.parsing.parsers.excel_parser import ExcelParser


def _write_workbook(path: Path, *, rows: int) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "问答"
    ws.append(["问题", "答案"])
    for index in range(1, rows + 1):
        ws.append([f"问题{index}", f"答案{index}"])
    wb.save(path)


def test_excel_parser_default_emits_all_rows_for_ingestion(tmp_path: Path) -> None:
    path = tmp_path / "qa.xlsx"
    _write_workbook(path, rows=75)

    docs = ExcelParser().parse(path)

    text = docs[0].page_content
    assert docs[0].metadata["excel_rows_emitted"] == 76
    assert "问题75" in text
    assert "答案75" in text
    assert docs[0].metadata.get("excel_truncated") is not True


def test_excel_parser_explicit_max_rows_still_truncates_for_preview(tmp_path: Path) -> None:
    path = tmp_path / "qa.xlsx"
    _write_workbook(path, rows=75)

    docs = ExcelParser(max_rows=10).parse(path)

    text = docs[0].page_content
    assert docs[0].metadata["excel_rows_emitted"] == 10
    assert "问题9" in text
    assert "问题75" not in text
    assert docs[0].metadata["excel_truncated"] is True

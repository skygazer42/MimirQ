from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest


def test_import_excel_error_hint_xls(monkeypatch, tmp_path: Path) -> None:
    import app.services.table_store_service as svc

    def boom(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("boom")

    monkeypatch.setattr(svc.pd, "ExcelFile", boom)

    with pytest.raises(RuntimeError) as excinfo:
        svc._import_excel(
            tenant_id=uuid4(),
            dataset_id=uuid4(),
            document_id=uuid4(),
            file_path=tmp_path / "x.xls",
            max_rows=10,
            max_cols=10,
            sample_rows=1,
        )

    msg = str(excinfo.value)
    assert "excel_open_failed" in msg
    assert "hint: install 'xlrd' for .xls support" in msg


def test_import_excel_error_hint_xlsx(monkeypatch, tmp_path: Path) -> None:
    import app.services.table_store_service as svc

    def boom(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("boom")

    monkeypatch.setattr(svc.pd, "ExcelFile", boom)

    with pytest.raises(RuntimeError) as excinfo:
        svc._import_excel(
            tenant_id=uuid4(),
            dataset_id=uuid4(),
            document_id=uuid4(),
            file_path=tmp_path / "x.xlsx",
            max_rows=10,
            max_cols=10,
            sample_rows=1,
        )

    msg = str(excinfo.value)
    assert "excel_open_failed" in msg
    assert "hint: install 'openpyxl' for .xlsx support" in msg


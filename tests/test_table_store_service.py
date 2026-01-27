from __future__ import annotations

import tempfile
from pathlib import Path
import uuid

import pytest


def test_table_store_table_id_parse_and_format():  # noqa: ANN001
    from app.services.table_store import format_table_id, parse_table_id

    doc_id = uuid.uuid4()
    tid = format_table_id(document_id=doc_id, sheet_index=3)
    assert tid.startswith("doc:")
    parsed = parse_table_id(tid)
    assert parsed is not None
    assert parsed.document_id == doc_id
    assert parsed.sheet_index == 3

    assert parse_table_id("doc:not-a-uuid:sheet:0") is None
    assert parse_table_id("doc:00000000-0000-0000-0000-000000000000:sheet:-1") is None
    assert parse_table_id("random") is None


def test_table_store_import_csv_and_query(monkeypatch):  # noqa: ANN001
    from app.core.config import settings
    from app.services.table_store_service import import_table_document, run_table_query

    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    document_id = uuid.uuid4()

    with tempfile.TemporaryDirectory() as td:
        monkeypatch.setattr(settings, "TABLE_STORE_DIR", str(Path(td) / "table_store"), raising=False)

        csv_path = Path(td) / "demo.csv"
        csv_path.write_text("a,b\n1,2\n3,4\n", encoding="utf-8")

        assets = import_table_document(
            tenant_id=tenant_id,
            dataset_id=dataset_id,
            document_id=document_id,
            file_path=csv_path,
            max_rows=10,
            max_cols=10,
            sample_rows=2,
        )
        assert len(assets) == 1
        assert assets[0].table_id.startswith(f"doc:{document_id}")
        assert assets[0].row_count == 2
        assert assets[0].col_count == 2

        res = run_table_query(
            tenant_id=tenant_id,
            dataset_id=dataset_id,
            table_id=assets[0].table_id,
            sql='SELECT * FROM "sheet_0"',
            max_rows=10,
            max_cols=10,
            max_bytes=100_000,
        )
        assert res["columns"] == ["a", "b"]
        assert res["rows"][0] == [1, 2]

        # Safety: reject non-SELECT
        with pytest.raises(Exception):
            run_table_query(
                tenant_id=tenant_id,
                dataset_id=dataset_id,
                table_id=assets[0].table_id,
                sql='DELETE FROM "sheet_0"',
                max_rows=10,
                max_cols=10,
                max_bytes=100_000,
            )

        # Safety: reject multi-statement
        with pytest.raises(Exception):
            run_table_query(
                tenant_id=tenant_id,
                dataset_id=dataset_id,
                table_id=assets[0].table_id,
                sql='SELECT 1; SELECT 2',
                max_rows=10,
                max_cols=10,
                max_bytes=100_000,
            )


def test_table_store_import_xlsx_and_query(monkeypatch):  # noqa: ANN001
    import pandas as pd  # type: ignore

    from app.core.config import settings
    from app.services.table_store_service import import_table_document, run_table_query

    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    document_id = uuid.uuid4()

    with tempfile.TemporaryDirectory() as td:
        monkeypatch.setattr(settings, "TABLE_STORE_DIR", str(Path(td) / "table_store"), raising=False)

        xlsx_path = Path(td) / "demo.xlsx"
        df = pd.DataFrame({"x": [10, 20], "y": ["a", "b"]})
        df.to_excel(str(xlsx_path), index=False)

        assets = import_table_document(
            tenant_id=tenant_id,
            dataset_id=dataset_id,
            document_id=document_id,
            file_path=xlsx_path,
            max_rows=10,
            max_cols=10,
            sample_rows=1,
        )
        assert len(assets) >= 1
        table_id = assets[0].table_id

        res = run_table_query(
            tenant_id=tenant_id,
            dataset_id=dataset_id,
            table_id=table_id,
            sql='SELECT * FROM "sheet_0"',
            max_rows=10,
            max_cols=10,
            max_bytes=100_000,
        )
        assert "x" in res["columns"]
        assert len(res["rows"]) >= 1


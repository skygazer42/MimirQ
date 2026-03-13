from __future__ import annotations

import tempfile
import uuid
from pathlib import Path

import pytest

from app.core.config import settings
from app.services.table_store_service import import_table_document, run_table_query


def test_table_query_rejects_overlong_sql(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(settings, "TABLE_QUERY_MAX_SQL_CHARS", 10, raising=False)
    table_id = f"doc:{uuid.uuid4()}:sheet:0"
    with pytest.raises(ValueError, match="sql_too_long"):
        run_table_query(
            tenant_id=uuid.uuid4(),
            dataset_id=uuid.uuid4(),
            table_id=table_id,
            sql="SELECT 1 " + ("x" * 100),
            max_rows=1,
            max_cols=1,
            max_bytes=1000,
        )


def test_table_query_join_rejects_unlisted_table(monkeypatch) -> None:  # noqa: ANN001
    import pandas as pd  # type: ignore

    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    document_id = uuid.uuid4()

    with tempfile.TemporaryDirectory() as td:
        monkeypatch.setattr(settings, "TABLE_STORE_DIR", str(Path(td) / "table_store"), raising=False)

        xlsx_path = Path(td) / "demo.xlsx"
        with pd.ExcelWriter(str(xlsx_path), engine="openpyxl") as writer:
            pd.DataFrame({"user_id": [1, 2], "amount": [10, 20]}).to_excel(writer, sheet_name="orders", index=False)
            pd.DataFrame({"id": [1, 2], "region": ["APAC", "EU"]}).to_excel(writer, sheet_name="users", index=False)

        import_table_document(
            tenant_id=tenant_id,
            dataset_id=dataset_id,
            document_id=document_id,
            file_path=xlsx_path,
            max_rows=100,
            max_cols=100,
            sample_rows=2,
        )

        table_id = f"doc:{document_id}:sheet:0"
        with pytest.raises(ValueError, match="table_reference_not_allowed"):
            run_table_query(
                tenant_id=tenant_id,
                dataset_id=dataset_id,
                table_id=table_id,
                sql=(
                    'SELECT u."region", o."amount" '
                    'FROM "sheet_0" AS o JOIN "sheet_1" AS u ON o."user_id" = u."id" '
                    "LIMIT 10"
                ),
                max_rows=10,
                max_cols=10,
                max_bytes=100_000,
            )


def test_table_query_join_allows_whitelisted_tables(monkeypatch) -> None:  # noqa: ANN001
    import pandas as pd  # type: ignore

    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    document_id = uuid.uuid4()

    with tempfile.TemporaryDirectory() as td:
        monkeypatch.setattr(settings, "TABLE_STORE_DIR", str(Path(td) / "table_store"), raising=False)

        xlsx_path = Path(td) / "demo.xlsx"
        with pd.ExcelWriter(str(xlsx_path), engine="openpyxl") as writer:
            pd.DataFrame({"user_id": [1, 2], "amount": [10, 20]}).to_excel(writer, sheet_name="orders", index=False)
            pd.DataFrame({"id": [1, 2], "region": ["APAC", "EU"]}).to_excel(writer, sheet_name="users", index=False)

        import_table_document(
            tenant_id=tenant_id,
            dataset_id=dataset_id,
            document_id=document_id,
            file_path=xlsx_path,
            max_rows=100,
            max_cols=100,
            sample_rows=2,
        )

        table_id = f"doc:{document_id}:sheet:0"
        got = run_table_query(
            tenant_id=tenant_id,
            dataset_id=dataset_id,
            table_id=table_id,
            sql=(
                'SELECT u."region", o."amount" '
                'FROM "sheet_0" AS o JOIN "sheet_1" AS u ON o."user_id" = u."id" '
                'ORDER BY o."amount" DESC LIMIT 10'
            ),
            max_rows=10,
            max_cols=10,
            max_bytes=100_000,
            allowed_sql_tables=["sheet_0", "sheet_1"],
        )
        assert got["columns"] == ["region", "amount"]
        assert got["rows"] == [["EU", 20], ["APAC", 10]]

from __future__ import annotations

import sqlite3
import uuid


def test_import_markdown_tables_creates_sqlite_and_asset(monkeypatch, tmp_path):  # noqa: ANN001
    from app.core.config import settings
    from app.services.table_store import table_store_path
    from app.services.table_store_service import import_markdown_tables

    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    document_id = uuid.uuid4()

    monkeypatch.setattr(settings, "TABLE_STORE_DIR", str(tmp_path / "table_store"), raising=False)

    markdown = "\n".join(
        [
            "| a | b |",
            "| --- | --- |",
            "| 1 | 2 |",
            "| 3 | 4 |",
        ]
    )

    assets = import_markdown_tables(
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        document_id=document_id,
        tables=[{"markdown": markdown, "sheet_name": "Page 1 Table 1"}],
        max_rows=0,
        max_cols=0,
        sample_rows=0,
    )
    assert len(assets) == 1
    asset = assets[0]
    assert asset.table_id == f"doc:{document_id}:sheet:0"
    assert asset.row_count == 2
    assert asset.col_count == 2
    assert [c.get("name") for c in (asset.columns or [])] == ["a", "b"]

    db_path = table_store_path(tenant_id=tenant_id, dataset_id=dataset_id, document_id=document_id)
    assert db_path.exists()
    conn = sqlite3.connect(str(db_path))
    try:
        cur = conn.execute('SELECT COUNT(1) FROM "sheet_0";')
        row = cur.fetchone()
        assert int(row[0] or 0) == 2
    finally:
        conn.close()


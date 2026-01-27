from __future__ import annotations

import uuid

import pytest

from app.core.config import settings
from app.services.table_store_service import run_table_query


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


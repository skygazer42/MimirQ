from __future__ import annotations

import hashlib
import uuid


class _InMemoryStore:
    def __init__(self) -> None:
        self.tables: list[dict] = []
        self.columns_by_table_id: dict[uuid.UUID, list[dict]] = {}

    def upsert_table(self, *, tenant_id: uuid.UUID, dataset_id: uuid.UUID, connector_config_id, table, seen_at):  # noqa: ANN001
        _ = (tenant_id, dataset_id, connector_config_id, seen_at)
        table_id = uuid.uuid4()
        self.tables.append({"id": table_id, "table": table})
        return table_id

    def replace_columns(self, *, table_id: uuid.UUID, columns):  # noqa: ANN001
        cols = list(columns or [])
        self.columns_by_table_id[table_id] = cols
        return len(cols)


def test_run_catalog_sync_persists_tables_and_columns(monkeypatch):  # noqa: ANN001
    from app.connectors.db import catalog_runner

    raw_tables = [
        {
            "db_name": "demo",
            "schema_name": "dbo",
            "table_name": "users",
            "table_type": "table",
            "comment": "user table",
            "columns": [
                {"ordinal": 1, "name": "id", "data_type": "int", "nullable": False},
                {"ordinal": 2, "name": "name", "data_type": "nvarchar", "nullable": True},
            ],
        },
        {
            "db_name": "demo",
            "schema_name": "dbo",
            "table_name": "orders",
            "table_type": "table",
            "columns": [],
        },
    ]

    monkeypatch.setattr(catalog_runner, "_introspect_sqlserver", lambda **_k: raw_tables, raising=False)

    store = _InMemoryStore()
    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()

    result = catalog_runner.run_catalog_sync(
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        connector_id="sqlserver_catalog",
        config={"host": "x", "database": "demo", "username": "svc", "password": "secret"},
        store=store,
    )

    assert result.get("engine") == "sqlserver"
    assert result.get("tables") == 2
    assert len(store.tables) == 2

    t0 = store.tables[0]["table"]
    expected_fp = hashlib.sha256("sqlserver|demo|dbo|users".encode("utf-8")).hexdigest()
    assert getattr(t0, "fingerprint") == expected_fp

    # columns persisted for the first table
    first_table_id = store.tables[0]["id"]
    assert len(store.columns_by_table_id.get(first_table_id) or []) == 2


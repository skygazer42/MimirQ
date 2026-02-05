from __future__ import annotations

import uuid


class _InMemoryStore:
    def __init__(self) -> None:
        self.profile_snapshots: list[dict] = []

    def upsert_table(self, *, tenant_id, dataset_id, connector_config_id, table, seen_at):  # noqa: ANN001
        _ = (tenant_id, dataset_id, connector_config_id, table, seen_at)
        return uuid.uuid4()

    def replace_columns(self, *, table_id, columns):  # noqa: ANN001
        _ = (table_id, columns)
        return 0

    def insert_profile_snapshot(self, *, table_id, entitlement_hash, profile, sample_meta):  # noqa: ANN001
        self.profile_snapshots.append(
            {
                "table_id": table_id,
                "entitlement_hash": entitlement_hash,
                "profile": profile,
                "sample_meta": sample_meta,
            }
        )
        return uuid.uuid4()


def test_run_catalog_sync_writes_table_profile_snapshots(monkeypatch):  # noqa: ANN001
    from app.connectors.db import catalog_runner

    raw_tables = [
        {"db_name": "demo", "schema_name": "dbo", "table_name": "users", "table_type": "table", "row_count_estimate": 123},
        {"db_name": "demo", "schema_name": "dbo", "table_name": "orders", "table_type": "table", "row_count_estimate": 456},
    ]

    monkeypatch.setattr(catalog_runner, "_introspect_sqlserver", lambda **_k: raw_tables, raising=False)

    store = _InMemoryStore()
    res = catalog_runner.run_catalog_sync(
        tenant_id=uuid.uuid4(),
        dataset_id=uuid.uuid4(),
        connector_id="sqlserver_catalog",
        config={"host": "x", "database": "demo", "username": "svc", "password": "secret", "profile_enabled": True},
        store=store,
    )

    assert res.get("engine") == "sqlserver"
    assert res.get("tables") == 2
    assert res.get("profiles_written") == 2
    assert len(store.profile_snapshots) == 2
    assert store.profile_snapshots[0]["profile"].get("row_count_estimate") == 123


from __future__ import annotations

import uuid


class _DummyQuery:
    def __init__(self, obj):  # noqa: ANN001
        self._obj = obj

    def options(self, *_a, **_k):  # noqa: ANN001
        return self

    def filter(self, *_a, **_k):  # noqa: ANN001
        return self

    def first(self):  # noqa: ANN201
        return self._obj


class _DummyDB:
    def __init__(self, run):  # noqa: ANN001
        self._run = run

    def query(self, *_a, **_k):  # noqa: ANN001
        return _DummyQuery(self._run)

    def commit(self) -> None:
        return None

    def refresh(self, _obj) -> None:  # noqa: ANN001
        return None

    def rollback(self) -> None:
        return None

    def close(self) -> None:
        return None


def test_execute_db_catalog_run_persists_row_snapshot_manifest(monkeypatch):  # noqa: ANN001
    import app.api.v1.connectors as connectors_module
    import app.connectors.db.catalog_runner as runner

    run_id = uuid.uuid4()
    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()

    class _Run:
        def __init__(self):  # noqa: D401
            self.id = run_id
            self.tenant_id = tenant_id
            self.connector_id = "mysql_catalog"
            self.dataset_id = dataset_id
            self.status = "pending"
            self.config = {
                "host": "x",
                "database": "demo",
                "username": "svc",
                "password": "secret",
                "row_sync_enabled": True,
                "row_sync_max_tables": 5,
                "row_sync_max_rows_per_table": 10,
                "row_sync_max_cols": 8,
            }
            self.stats = {}
            self.documents = []

            self.started_at = None
            self.finished_at = None
            self.error_message = None

    run = _Run()
    dummy_db = _DummyDB(run)
    monkeypatch.setattr(connectors_module, "SessionLocal", lambda: dummy_db, raising=True)
    monkeypatch.setattr(connectors_module.settings, "DB_CATALOG_ROW_SYNC_ENABLED", True, raising=False)

    def _fake_run_catalog_sync(**_kwargs):  # noqa: ANN001
        return {"engine": "mysql", "tables": 1, "tables_upserted": 1, "columns_upserted": 2}

    monkeypatch.setattr(runner, "run_catalog_sync", _fake_run_catalog_sync, raising=True)
    monkeypatch.setattr(
        runner,
        "extract_row_snapshots",
        lambda **_kwargs: [
            {
                "source_table": "demo.users",
                "source_sync_token": "tok-users-v1",
                "rows": [{"id": 1, "__row_pk_hash": "pkhash-1"}],
            }
        ],
        raising=True,
    )
    monkeypatch.setattr(
        connectors_module,
        "_upsert_db_row_sidecar_document",
        lambda **_kwargs: {"document_id": str(uuid.uuid4()), "tables": 1, "source_manifest_count": 1},
        raising=True,
    )

    connectors_module._execute_db_catalog_run(run_id=run_id, tenant_id=tenant_id, requested_by="tester")

    assert run.status == "completed"
    assert isinstance(run.stats, dict)
    assert run.stats.get("total_tables") == 1
    assert run.stats.get("source_manifest") == {"demo.users": "tok-users-v1"}
    assert isinstance(run.stats.get("row_sidecar"), dict)

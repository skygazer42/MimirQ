from __future__ import annotations

import uuid

import pytest


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
        self.commits = 0

    def query(self, *_a, **_k):  # noqa: ANN001
        return _DummyQuery(self._run)

    def commit(self) -> None:
        self.commits += 1

    def refresh(self, _obj) -> None:  # noqa: ANN001
        return None

    def rollback(self) -> None:
        return None

    def close(self) -> None:
        return None


@pytest.mark.asyncio
async def test_execute_db_catalog_run_attempts_virtual_schema_doc(monkeypatch):  # noqa: ANN001
    import app.api.v1.connectors as connectors_module
    import app.connectors.db.catalog_runner as runner
    import app.services.db_catalog_observability as obs
    import app.services.db_catalog_schema_doc_service as schema_doc

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
            self.config = {"host": "x", "database": "demo", "username": "svc", "password": "secret"}
            self.stats = {}
            self.documents = []

            self.started_at = None
            self.finished_at = None
            self.error_message = None

    run = _Run()
    dummy_db = _DummyDB(run)
    monkeypatch.setattr(connectors_module, "SessionLocal", lambda: dummy_db, raising=True)

    def _fake_run_catalog_sync(**_kwargs):  # noqa: ANN001
        return {"engine": "mysql", "tables": 1, "tables_upserted": 1, "columns_upserted": 2, "profiles_written": 0}

    monkeypatch.setattr(runner, "run_catalog_sync", _fake_run_catalog_sync, raising=True)

    called: dict = {"schema_doc": 0, "metrics_doc": 0}

    def _fake_upsert_and_index_virtual_schema_doc(**kwargs):  # noqa: ANN001
        called["schema_doc"] += 1
        assert kwargs["tenant_id"] == tenant_id
        assert kwargs["dataset_id"] == dataset_id
        assert kwargs["connector_run_id"] == run_id
        return {"document_id": str(uuid.uuid4()), "tables": 1, "chunks": 2}

    monkeypatch.setattr(schema_doc, "upsert_and_index_virtual_schema_doc", _fake_upsert_and_index_virtual_schema_doc, raising=True)

    def _fake_emit_db_catalog_schema_doc_completed(**_kwargs):  # noqa: ANN001
        called["metrics_doc"] += 1

    monkeypatch.setattr(obs, "emit_db_catalog_schema_doc_completed", _fake_emit_db_catalog_schema_doc_completed, raising=True)

    await connectors_module._execute_db_catalog_run(run_id=run_id, tenant_id=tenant_id, requested_by="tester")

    assert called["schema_doc"] == 1
    assert called["metrics_doc"] == 1
    assert run.status == "completed"
    assert isinstance(run.stats, dict)
    assert "schema_doc" in run.stats


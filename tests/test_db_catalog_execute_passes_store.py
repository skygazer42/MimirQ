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


def test_execute_db_catalog_run_passes_store_to_runner(monkeypatch):  # noqa: ANN001
    import app.api.v1.connectors as connectors_module
    import app.connectors.db.catalog_runner as runner

    run_id = uuid.uuid4()
    tenant_id = uuid.uuid4()

    class _Run:
        def __init__(self):  # noqa: D401
            self.id = run_id
            self.tenant_id = tenant_id
            self.connector_id = "sqlserver_catalog"
            self.dataset_id = uuid.uuid4()
            self.status = "pending"
            self.config = {"host": "x", "database": "demo", "username": "svc", "password": "secret"}
            self.stats = {}
            self.documents = []

            self.started_at = None
            self.finished_at = None
            self.error_message = None

    dummy_db = _DummyDB(_Run())
    monkeypatch.setattr(connectors_module, "SessionLocal", lambda: dummy_db, raising=True)

    called: dict = {}

    def _fake_run_catalog_sync(**kwargs):  # noqa: ANN001
        called.update(kwargs)
        return {"engine": "sqlserver", "tables": 0}

    monkeypatch.setattr(runner, "run_catalog_sync", _fake_run_catalog_sync, raising=True)

    connectors_module._execute_db_catalog_run(run_id=run_id, tenant_id=tenant_id, requested_by="tester")

    assert "store" in called
    assert called["store"] is not None

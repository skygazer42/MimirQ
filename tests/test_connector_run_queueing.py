from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.core.database import get_db


class _DummyDB:
    def __init__(self) -> None:
        self.added: list[object] = []

    def add(self, obj) -> None:  # noqa: ANN001
        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()
        if getattr(obj, "created_at", None) is None:
            obj.created_at = datetime.now(timezone.utc)
        if getattr(obj, "documents", None) is None:
            obj.documents = []
        self.added.append(obj)

    def commit(self) -> None:
        return None

    def refresh(self, obj) -> None:  # noqa: ANN001
        self.add(obj)

    def query(self, model):  # noqa: ANN001
        raise NotImplementedError("query() should be monkeypatched per test")


def _override_get_db(dummy_db: _DummyDB):  # noqa: ANN202
    def _impl():  # noqa: ANN202
        yield dummy_db

    return _impl


def _override_get_tenant_id() -> uuid.UUID:
    return uuid.uuid4()


def _override_get_current_account_id() -> str:
    return "test-account"


def test_connectors_create_run_sets_task_id_when_queue_enabled(monkeypatch):  # noqa: ANN001
    import app.api.v1.connectors as connectors_module
    from app.api.v1.connectors import create_connector_run
    from app.core.config import settings

    monkeypatch.setattr(settings, "URL_INGEST_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "TASK_QUEUE_ENABLED", True, raising=False)

    monkeypatch.setattr(connectors_module.DatasetService, "ensure_member", lambda *_a, **_k: None, raising=True)

    dataset_id = uuid.uuid4()

    class _Dataset:
        def __init__(self, dataset_id: uuid.UUID):  # noqa: ANN001
            self.id = dataset_id

    monkeypatch.setattr(
        connectors_module,
        "_resolve_writable_dataset",
        lambda *_a, **_k: _Dataset(dataset_id),
        raising=True,
    )

    async def _fake_enqueue(*_a, **_k):  # noqa: ANN202
        return "job-123"

    monkeypatch.setattr(connectors_module, "enqueue_connector_run", _fake_enqueue, raising=False)

    dummy_db = _DummyDB()
    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db(dummy_db)
    app.dependency_overrides[get_tenant_id] = _override_get_tenant_id
    app.dependency_overrides[get_current_account_id] = _override_get_current_account_id
    app.post("/api/v1/connectors/runs", status_code=201)(create_connector_run)
    client = TestClient(app)

    res = client.post(
        "/api/v1/connectors/runs",
        json={
            "connector_id": "url_batch",
            "dataset_id": str(dataset_id),
            "config": {"urls": ["https://example.com/a.txt"]},
        },
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body.get("task_id") == "job-123"


def test_connector_run_retry_failed_sets_task_id_when_queue_enabled(monkeypatch):  # noqa: ANN001
    import app.api.v1.connectors as connectors_module
    from app.core.config import settings
    from app.models.connector import ConnectorRun

    monkeypatch.setattr(settings, "URL_INGEST_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "TASK_QUEUE_ENABLED", True, raising=False)

    monkeypatch.setattr(connectors_module.DatasetService, "ensure_member", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(connectors_module.DatasetService, "get_dataset", lambda *_a, **_k: object(), raising=True)
    monkeypatch.setattr(connectors_module.DatasetService, "assert_dataset_writable", lambda *_a, **_k: None, raising=True)

    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    run_id = uuid.uuid4()

    class _DummyRun:
        def __init__(self) -> None:
            self.id = run_id
            self.tenant_id = tenant_id
            self.dataset_id = dataset_id
            self.connector_id = "url_batch"
            self.requested_by = "test-account"
            self.status = "completed"
            self.config = {"urls": ["https://example.com/a.txt", "https://example.com/b.txt"]}
            self.stats = {"failed_urls": ["https://example.com/b.txt"], "created": 1, "failed": 1}
            self.error_message = None
            self.task_id = None
            self.created_at = datetime.now(timezone.utc)
            self.started_at = datetime.now(timezone.utc)
            self.finished_at = datetime.now(timezone.utc)
            self.documents = []

    dummy_run = _DummyRun()

    class _DummyQuery:
        def __init__(self, model):  # noqa: ANN001
            self.model = model

        def filter(self, *_a, **_k):  # noqa: ANN001
            return self

        def first(self):  # noqa: ANN001
            if self.model is ConnectorRun:
                return dummy_run
            return None

    class _DB(_DummyDB):
        def query(self, model):  # noqa: ANN001
            return _DummyQuery(model)

    async def _fake_enqueue(*_a, **_k):  # noqa: ANN202
        return "job-456"

    monkeypatch.setattr(connectors_module, "enqueue_connector_run", _fake_enqueue, raising=False)

    dummy_db = _DB()

    def _override_get_tenant_id() -> uuid.UUID:
        return tenant_id

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db(dummy_db)
    app.dependency_overrides[get_tenant_id] = _override_get_tenant_id
    app.dependency_overrides[get_current_account_id] = _override_get_current_account_id
    app.include_router(connectors_module.router, prefix="/api/v1/connectors")
    client = TestClient(app)

    res = client.post(f"/api/v1/connectors/runs/{run_id}/retry-failed")
    assert res.status_code == 201, res.text
    body = res.json()
    assert body.get("task_id") == "job-456"


def test_connector_run_resume_sets_task_id_when_queue_enabled(monkeypatch):  # noqa: ANN001
    import app.api.v1.connectors as connectors_module
    from app.core.config import settings
    from app.models.connector import ConnectorRun

    monkeypatch.setattr(settings, "URL_INGEST_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "TASK_QUEUE_ENABLED", True, raising=False)

    monkeypatch.setattr(connectors_module.DatasetService, "ensure_member", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(connectors_module.DatasetService, "get_dataset", lambda *_a, **_k: object(), raising=True)
    monkeypatch.setattr(connectors_module.DatasetService, "assert_dataset_writable", lambda *_a, **_k: None, raising=True)

    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    run_id = uuid.uuid4()

    class _DummyRun:
        def __init__(self) -> None:
            self.id = run_id
            self.tenant_id = tenant_id
            self.dataset_id = dataset_id
            self.connector_id = "url_batch"
            self.requested_by = "test-account"
            self.status = "cancelled"
            self.config = {"urls": ["https://example.com/1.txt", "https://example.com/2.txt"]}
            self.stats = {"cursor": 1, "processed_urls": 1}
            self.error_message = None
            self.task_id = None
            self.created_at = datetime.now(timezone.utc)
            self.started_at = datetime.now(timezone.utc)
            self.finished_at = datetime.now(timezone.utc)
            self.documents = []

    dummy_run = _DummyRun()

    class _DummyQuery:
        def __init__(self, model):  # noqa: ANN001
            self.model = model

        def filter(self, *_a, **_k):  # noqa: ANN001
            return self

        def first(self):  # noqa: ANN001
            if self.model is ConnectorRun:
                return dummy_run
            return None

    class _DB(_DummyDB):
        def query(self, model):  # noqa: ANN001
            return _DummyQuery(model)

    async def _fake_enqueue(*_a, **_k):  # noqa: ANN202
        return "job-789"

    monkeypatch.setattr(connectors_module, "enqueue_connector_run", _fake_enqueue, raising=False)

    dummy_db = _DB()

    def _override_get_tenant_id() -> uuid.UUID:
        return tenant_id

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db(dummy_db)
    app.dependency_overrides[get_tenant_id] = _override_get_tenant_id
    app.dependency_overrides[get_current_account_id] = _override_get_current_account_id
    app.include_router(connectors_module.router, prefix="/api/v1/connectors")
    client = TestClient(app)

    res = client.post(f"/api/v1/connectors/runs/{run_id}/resume")
    assert res.status_code == 201, res.text
    body = res.json()
    assert body.get("task_id") == "job-789"


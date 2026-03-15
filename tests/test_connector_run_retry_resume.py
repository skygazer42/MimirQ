from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.core.database import get_db


def test_connector_run_retry_failed_creates_new_run(monkeypatch):  # noqa: ANN001
    import app.api.v1.connectors as connectors_module
    from app.core.config import settings
    from app.models.connector import ConnectorRun

    monkeypatch.setattr(settings, "URL_INGEST_ENABLED", True, raising=False)
    monkeypatch.setattr(connectors_module.DatasetService, "ensure_member", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(connectors_module.DatasetService, "get_dataset", lambda *_a, **_k: object(), raising=True)
    monkeypatch.setattr(connectors_module.DatasetService, "assert_dataset_writable", lambda *_a, **_k: None, raising=True)

    async def _noop_async(*_a, **_k):  # noqa: ANN202
        await asyncio.sleep(0)  # Sonar S7503
        return None

    monkeypatch.setattr(connectors_module, "_execute_url_batch_run", _noop_async, raising=True)

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
            self.created_at = datetime.now(UTC)
            self.started_at = datetime.now(UTC)
            self.finished_at = datetime.now(UTC)
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

    class _DummyDB:
        def __init__(self) -> None:
            self.added: list[object] = []

        def query(self, model):  # noqa: ANN001
            return _DummyQuery(model)

        def add(self, obj) -> None:  # noqa: ANN001
            # Mimic DB-side defaults for unit tests.
            if getattr(obj, "id", None) is None:
                obj.id = uuid.uuid4()
            if getattr(obj, "created_at", None) is None:
                obj.created_at = datetime.now(UTC)
            if getattr(obj, "documents", None) is None:
                obj.documents = []
            self.added.append(obj)

        def commit(self) -> None:
            return None

        def refresh(self, obj) -> None:  # noqa: ANN001
            self.add(obj)

    dummy_db = _DummyDB()

    def _override_get_db():  # noqa: ANN202
        yield dummy_db

    def _override_get_tenant_id() -> uuid.UUID:
        return tenant_id

    def _override_get_current_account_id() -> str:
        return "test-account"

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = _override_get_tenant_id
    app.dependency_overrides[get_current_account_id] = _override_get_current_account_id
    app.include_router(connectors_module.router, prefix="/api/v1/connectors")
    client = TestClient(app)

    res = client.post(f"/api/v1/connectors/runs/{run_id}/retry-failed")
    assert res.status_code == 201, res.text
    body = res.json()
    assert body.get("connector_id") == "url_batch"
    assert (body.get("config") or {}).get("urls") == ["https://example.com/b.txt"]
    assert (body.get("stats") or {}).get("retry_of") == str(run_id)


def test_connector_run_resume_uses_cursor(monkeypatch):  # noqa: ANN001
    import app.api.v1.connectors as connectors_module
    from app.core.config import settings
    from app.models.connector import ConnectorRun

    monkeypatch.setattr(settings, "URL_INGEST_ENABLED", True, raising=False)
    monkeypatch.setattr(connectors_module.DatasetService, "ensure_member", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(connectors_module.DatasetService, "get_dataset", lambda *_a, **_k: object(), raising=True)
    monkeypatch.setattr(connectors_module.DatasetService, "assert_dataset_writable", lambda *_a, **_k: None, raising=True)

    async def _noop_async(*_a, **_k):  # noqa: ANN202
        await asyncio.sleep(0)  # Sonar S7503
        return None

    monkeypatch.setattr(connectors_module, "_execute_url_batch_run", _noop_async, raising=True)

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
            self.config = {"urls": ["https://example.com/1.txt", "https://example.com/2.txt", "https://example.com/3.txt"]}
            self.stats = {"cursor": 1, "processed_urls": 1}
            self.error_message = None
            self.task_id = None
            self.created_at = datetime.now(UTC)
            self.started_at = datetime.now(UTC)
            self.finished_at = datetime.now(UTC)
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

    class _DummyDB:
        def __init__(self) -> None:
            self.added: list[object] = []

        def query(self, model):  # noqa: ANN001
            return _DummyQuery(model)

        def add(self, obj) -> None:  # noqa: ANN001
            if getattr(obj, "id", None) is None:
                obj.id = uuid.uuid4()
            if getattr(obj, "created_at", None) is None:
                obj.created_at = datetime.now(UTC)
            if getattr(obj, "documents", None) is None:
                obj.documents = []
            self.added.append(obj)

        def commit(self) -> None:
            return None

        def refresh(self, obj) -> None:  # noqa: ANN001
            self.add(obj)

    dummy_db = _DummyDB()

    def _override_get_db():  # noqa: ANN202
        yield dummy_db

    def _override_get_tenant_id() -> uuid.UUID:
        return tenant_id

    def _override_get_current_account_id() -> str:
        return "test-account"

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = _override_get_tenant_id
    app.dependency_overrides[get_current_account_id] = _override_get_current_account_id
    app.include_router(connectors_module.router, prefix="/api/v1/connectors")
    client = TestClient(app)

    res = client.post(f"/api/v1/connectors/runs/{run_id}/resume")
    assert res.status_code == 201, res.text
    body = res.json()
    assert (body.get("config") or {}).get("urls") == ["https://example.com/2.txt", "https://example.com/3.txt"]
    assert (body.get("stats") or {}).get("resume_of") == str(run_id)


def test_connector_run_resume_builds_state_for_web_crawl(monkeypatch):  # noqa: ANN001
    import app.api.v1.connectors as connectors_module
    from app.core.config import settings
    from app.models.connector import ConnectorRun

    monkeypatch.setattr(settings, "URL_INGEST_ENABLED", True, raising=False)
    monkeypatch.setattr(connectors_module.DatasetService, "ensure_member", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(connectors_module.DatasetService, "get_dataset", lambda *_a, **_k: object(), raising=True)
    monkeypatch.setattr(connectors_module.DatasetService, "assert_dataset_writable", lambda *_a, **_k: None, raising=True)

    async def _noop_async(*_a, **_k):  # noqa: ANN202
        await asyncio.sleep(0)  # Sonar S7503
        return None

    monkeypatch.setattr(connectors_module, "_execute_web_crawl_run", _noop_async, raising=True)

    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    run_id = uuid.uuid4()

    class _DummyRun:
        def __init__(self) -> None:
            self.id = run_id
            self.tenant_id = tenant_id
            self.dataset_id = dataset_id
            self.connector_id = "web_crawl"
            self.requested_by = "test-account"
            self.status = "failed"
            self.config = {"start_urls": ["https://example.com/docs"], "max_pages": 20}
            self.stats = {"cursor": 3, "processed_urls": 3, "total_urls": 9}
            self.error_message = "boom"
            self.task_id = None
            self.created_at = datetime.now(UTC)
            self.started_at = datetime.now(UTC)
            self.finished_at = datetime.now(UTC)
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

    class _DummyDB:
        def __init__(self) -> None:
            self.added: list[object] = []

        def query(self, model):  # noqa: ANN001
            return _DummyQuery(model)

        def add(self, obj) -> None:  # noqa: ANN001
            if getattr(obj, "id", None) is None:
                obj.id = uuid.uuid4()
            if getattr(obj, "created_at", None) is None:
                obj.created_at = datetime.now(UTC)
            if getattr(obj, "documents", None) is None:
                obj.documents = []
            self.added.append(obj)

        def commit(self) -> None:
            return None

        def refresh(self, obj) -> None:  # noqa: ANN001
            self.add(obj)

    dummy_db = _DummyDB()

    def _override_get_db():  # noqa: ANN202
        yield dummy_db

    def _override_get_tenant_id() -> uuid.UUID:
        return tenant_id

    def _override_get_current_account_id() -> str:
        return "test-account"

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = _override_get_tenant_id
    app.dependency_overrides[get_current_account_id] = _override_get_current_account_id
    app.include_router(connectors_module.router, prefix="/api/v1/connectors")
    client = TestClient(app)

    res = client.post(f"/api/v1/connectors/runs/{run_id}/resume")
    assert res.status_code == 201, res.text
    body = res.json()
    assert body.get("connector_id") == "web_crawl"
    assert (body.get("config") or {}).get("start_urls") == ["https://example.com/docs"]
    assert ((body.get("config") or {}).get("_state") or {}).get("cursor") == 3
    assert ((body.get("config") or {}).get("_state") or {}).get("total_urls") == 9
    assert (body.get("stats") or {}).get("resume_of") == str(run_id)


def test_connector_run_resume_allows_incremental_github_manifest_even_when_cursor_is_exhausted(monkeypatch):  # noqa: ANN001
    import app.api.v1.connectors as connectors_module
    from app.core.config import settings
    from app.models.connector import ConnectorRun

    monkeypatch.setattr(settings, "URL_INGEST_ENABLED", True, raising=False)
    monkeypatch.setattr(connectors_module.DatasetService, "ensure_member", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(connectors_module.DatasetService, "get_dataset", lambda *_a, **_k: object(), raising=True)
    monkeypatch.setattr(connectors_module.DatasetService, "assert_dataset_writable", lambda *_a, **_k: None, raising=True)

    async def _noop_async(*_a, **_k):  # noqa: ANN202
        await asyncio.sleep(0)  # Sonar S7503
        return None

    monkeypatch.setattr(connectors_module, "_execute_github_repo_run", _noop_async, raising=True)

    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    run_id = uuid.uuid4()

    class _DummyRun:
        def __init__(self) -> None:
            self.id = run_id
            self.tenant_id = tenant_id
            self.dataset_id = dataset_id
            self.connector_id = "github_repo"
            self.requested_by = "test-account"
            self.status = "failed"
            self.config = {"repo": "acme/docs", "branch": "main"}
            self.stats = {
                "cursor": 2,
                "total_files": 2,
                "source_manifest": {"a.md": "sha-a-old", "b.md": "sha-b"},
            }
            self.error_message = "boom"
            self.task_id = None
            self.created_at = datetime.now(UTC)
            self.started_at = datetime.now(UTC)
            self.finished_at = datetime.now(UTC)
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

    class _DummyDB:
        def __init__(self) -> None:
            self.added: list[object] = []

        def query(self, model):  # noqa: ANN001
            return _DummyQuery(model)

        def add(self, obj) -> None:  # noqa: ANN001
            if getattr(obj, "id", None) is None:
                obj.id = uuid.uuid4()
            if getattr(obj, "created_at", None) is None:
                obj.created_at = datetime.now(UTC)
            if getattr(obj, "documents", None) is None:
                obj.documents = []
            self.added.append(obj)

        def commit(self) -> None:
            return None

        def refresh(self, obj) -> None:  # noqa: ANN001
            self.add(obj)

    dummy_db = _DummyDB()

    def _override_get_db():  # noqa: ANN202
        yield dummy_db

    def _override_get_tenant_id() -> uuid.UUID:
        return tenant_id

    def _override_get_current_account_id() -> str:
        return "test-account"

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = _override_get_tenant_id
    app.dependency_overrides[get_current_account_id] = _override_get_current_account_id
    app.include_router(connectors_module.router, prefix="/api/v1/connectors")
    client = TestClient(app)

    res = client.post(f"/api/v1/connectors/runs/{run_id}/resume")
    assert res.status_code == 201, res.text
    body = res.json()
    assert body.get("connector_id") == "github_repo"
    assert ((body.get("config") or {}).get("_state") or {}).get("cursor") == 2
    assert ((body.get("config") or {}).get("_state") or {}).get("source_manifest") == {
        "a.md": "sha-a-old",
        "b.md": "sha-b",
    }
    assert (body.get("stats") or {}).get("resume_of") == str(run_id)

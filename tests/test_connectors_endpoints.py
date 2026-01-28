from __future__ import annotations

from datetime import datetime, timezone
import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.api.schemas.connector import ConnectorInfo, ConnectorRunOut
from app.core.database import get_db


class _DummyDB:
    def add(self, obj) -> None:  # noqa: ANN001
        # Mimic a few DB-side defaults for unit tests.
        if getattr(obj, "id", None) is None:
            setattr(obj, "id", uuid.uuid4())
        if getattr(obj, "created_at", None) is None:
            setattr(obj, "created_at", datetime.now(timezone.utc))
        if getattr(obj, "documents", None) is None:
            setattr(obj, "documents", [])

    def commit(self) -> None:
        return None

    def refresh(self, obj) -> None:  # noqa: ANN001
        # Apply the same defaults on refresh.
        self.add(obj)


def _override_get_db():  # noqa: ANN202
    yield _DummyDB()


def _override_get_tenant_id() -> uuid.UUID:
    return uuid.uuid4()


def _override_get_current_account_id() -> str:
    return "test-account"


def test_connectors_list_contains_url_batch():  # noqa: ANN001
    from app.api.v1.connectors import list_connectors

    app = FastAPI()
    app.get("/api/v1/connectors", response_model=list[ConnectorInfo])(list_connectors)
    client = TestClient(app)

    res = client.get("/api/v1/connectors")
    assert res.status_code == 200, res.text
    items = res.json()
    assert any(item.get("id") == "url_batch" for item in items)
    assert any(item.get("id") == "web_crawl" for item in items)


def test_connectors_create_run_requires_url_ingest_enabled(monkeypatch):  # noqa: ANN001
    from app.api.v1.connectors import create_connector_run
    from app.core.config import settings

    monkeypatch.setattr(settings, "URL_INGEST_ENABLED", False, raising=False)

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = _override_get_tenant_id
    app.dependency_overrides[get_current_account_id] = _override_get_current_account_id
    app.post("/api/v1/connectors/runs", status_code=201, response_model=ConnectorRunOut)(create_connector_run)
    client = TestClient(app)

    res = client.post(
        "/api/v1/connectors/runs",
        json={
            "connector_id": "url_batch",
            "dataset_id": str(uuid.uuid4()),
            "config": {"urls": ["https://example.com/a.txt"]},
        },
    )
    assert res.status_code == 400, res.text


def test_connectors_create_run_happy_path(monkeypatch):  # noqa: ANN001
    from app.api.v1.connectors import create_connector_run
    import app.api.v1.connectors as connectors_module
    from app.core.config import settings

    monkeypatch.setattr(settings, "URL_INGEST_ENABLED", True, raising=False)

    # Bypass dataset permission enforcement for unit test (covered elsewhere).
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

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = _override_get_tenant_id
    app.dependency_overrides[get_current_account_id] = _override_get_current_account_id
    app.post("/api/v1/connectors/runs", status_code=201, response_model=ConnectorRunOut)(create_connector_run)
    client = TestClient(app)

    res = client.post(
        "/api/v1/connectors/runs",
        json={
            "connector_id": "url_batch",
            "dataset_id": str(dataset_id),
            "config": {
                "urls": ["https://example.com/a.txt", "https://example.com/b.txt"],
                "parser_backend": "auto",
                "chunk_strategy": "langchain_recursive",
                "access": {"mode": "inherit"},
            },
        },
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body.get("connector_id") == "url_batch"
    assert body.get("dataset_id") == str(dataset_id)
    assert body.get("status") == "pending"
    assert (body.get("config") or {}).get("urls") == ["https://example.com/a.txt", "https://example.com/b.txt"]


def test_connectors_create_web_crawl_run_redacts_auth(monkeypatch):  # noqa: ANN001
    from app.api.v1.connectors import create_connector_run
    import app.api.v1.connectors as connectors_module
    from app.core.config import settings

    monkeypatch.setattr(settings, "URL_INGEST_ENABLED", True, raising=False)
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

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = _override_get_tenant_id
    app.dependency_overrides[get_current_account_id] = _override_get_current_account_id
    app.post("/api/v1/connectors/runs", status_code=201, response_model=ConnectorRunOut)(create_connector_run)
    client = TestClient(app)

    res = client.post(
        "/api/v1/connectors/runs",
        json={
            "connector_id": "web_crawl",
            "dataset_id": str(dataset_id),
            "config": {
                "start_urls": ["https://example.com"],
                "auth": {"type": "bearer", "token": "secret-token"},
                "max_pages": 1,
                "max_depth": 0,
            },
        },
    )
    assert res.status_code == 201, res.text
    body = res.json()
    cfg = body.get("config") or {}
    assert cfg.get("auth", {}).get("token") == "<redacted>"


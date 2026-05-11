from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies.auth import get_current_account_id  # noqa: E402
from app.api.dependencies.tenant import get_tenant_id  # noqa: E402
from app.api.schemas.connector import ConnectorInfo, ConnectorRunOut  # noqa: E402
from app.core.database import get_db  # noqa: E402


class _DummyDB:
    def add(self, obj) -> None:  # noqa: ANN001
        # Mimic a few DB-side defaults for unit tests.
        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()
        if getattr(obj, "created_at", None) is None:
            obj.created_at = datetime.now(UTC)
        if getattr(obj, "documents", None) is None:
            obj.documents = []

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
    from app.api.v1.connectors_catalog import list_connectors

    app = FastAPI()
    app.get("/api/v1/connectors", response_model=list[ConnectorInfo])(list_connectors)
    client = TestClient(app)

    res = client.get("/api/v1/connectors")
    assert res.status_code == 200, res.text
    items = res.json()
    assert any(item.get("id") == "url_batch" for item in items)
    assert any(item.get("id") == "web_crawl" for item in items)
    assert any(item.get("id") == "confluence_space" for item in items)
    assert any(item.get("id") == "jira_project" for item in items)


def test_connectors_list_exposes_resume_capabilities():  # noqa: ANN001
    from app.api.v1.connectors_catalog import list_connectors

    app = FastAPI()
    app.get("/api/v1/connectors", response_model=list[ConnectorInfo])(list_connectors)
    client = TestClient(app)

    res = client.get("/api/v1/connectors")
    assert res.status_code == 200, res.text

    items = {item.get("id"): item for item in res.json()}
    assert items["url_batch"]["supports_incremental"] is True
    assert items["url_batch"]["supports_resume"] is True
    assert items["url_batch"]["supports_full_reconcile"] is False
    assert items["url_batch"]["sync_cursor_kind"] == "offset"
    assert items["web_crawl"]["supports_incremental"] is True
    assert items["web_crawl"]["supports_resume"] is True
    assert items["web_crawl"]["supports_full_reconcile"] is True
    assert items["web_crawl"]["sync_cursor_kind"] == "offset"
    assert items["github_repo"]["supports_incremental"] is True
    assert items["github_repo"]["supports_resume"] is True
    assert items["github_repo"]["supports_full_reconcile"] is True
    assert items["github_repo"]["sync_cursor_kind"] == "offset"
    assert items["drive_files"]["supports_resume"] is True
    assert items["drive_files"]["supports_incremental"] is True
    assert items["drive_files"]["supports_full_reconcile"] is True
    assert items["drive_files"]["sync_cursor_kind"] == "offset"
    assert items["minio_bucket"]["supports_resume"] is True
    assert items["minio_bucket"]["supports_incremental"] is True
    assert items["minio_bucket"]["supports_full_reconcile"] is True
    assert items["minio_bucket"]["sync_cursor_kind"] == "offset"
    assert items["confluence_space"]["supports_incremental"] is True
    assert items["confluence_space"]["supports_resume"] is False
    assert items["confluence_space"]["supports_full_reconcile"] is True
    assert items["confluence_space"]["sync_cursor_kind"] == "timestamp"
    assert items["jira_project"]["supports_incremental"] is True
    assert items["jira_project"]["supports_resume"] is False
    assert items["jira_project"]["supports_full_reconcile"] is True
    assert items["jira_project"]["sync_cursor_kind"] == "timestamp"


def test_parse_link_header_next_extracts_rel_next_url() -> None:
    import app.api.v1.connectors as connectors_module

    next_url = "https://api.github.com/repos/acme/project/teams?page=2"
    header = (
        f'<{next_url}>; rel="next", '
        '<https://api.github.com/repos/acme/project/teams?page=9>; rel="last"'
    )

    assert connectors_module._parse_link_header_next(header) == next_url


def test_connector_run_completion_status_only_fails_when_nothing_was_created() -> None:
    import app.api.v1.connectors as connectors_module

    assert connectors_module._connector_run_completion_status(created=2, failed=0) == "completed"
    assert connectors_module._connector_run_completion_status(created=2, failed=1) == "completed"
    assert connectors_module._connector_run_completion_status(created=0, failed=1) == "failed"


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
    import app.api.v1.connectors as connectors_module
    from app.api.v1.connectors import create_connector_run
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


def test_connectors_create_run_rejects_unknown_source_acl_groups(monkeypatch):  # noqa: ANN001
    import app.api.v1.connectors as connectors_module
    from app.api.v1.connectors import create_connector_run
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

    missing_group_id = uuid.uuid4()
    monkeypatch.setattr(
        connectors_module,
        "_unknown_tenant_groups",
        lambda *_a, **_k: [str(missing_group_id)],
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
                "urls": ["https://example.com/a.txt"],
                "source_acl": {
                    "mode": "inherit",
                    "group_mappings": [
                        {
                            "source": {"system": "github", "kind": "team", "id": "acme/dev"},
                            "group_id": str(missing_group_id),
                        }
                    ],
                },
            },
        },
    )
    assert res.status_code == 400, res.text
    assert "Unknown tenant groups" in (res.json() or {}).get("detail", "")


def test_connectors_create_run_rejects_unknown_access_groups(monkeypatch):  # noqa: ANN001
    import app.api.v1.connectors as connectors_module
    from app.api.v1.connectors import create_connector_run
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

    missing_group_id = uuid.uuid4()
    monkeypatch.setattr(
        connectors_module,
        "_unknown_tenant_groups",
        lambda *_a, **_k: [str(missing_group_id)],
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
                "urls": ["https://example.com/a.txt"],
                "access": {"mode": "partial_members", "partial_group_list": [str(missing_group_id)]},
            },
        },
    )
    assert res.status_code == 400, res.text
    assert "Unknown tenant groups" in (res.json() or {}).get("detail", "")


def test_connectors_create_web_crawl_run_redacts_auth(monkeypatch):  # noqa: ANN001
    import app.api.v1.connectors as connectors_module
    from app.api.v1.connectors import create_connector_run
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

def test_connectors_create_confluence_run_redacts_auth(monkeypatch):  # noqa: ANN001
    import app.api.v1.connectors as connectors_module
    from app.api.v1.connectors import create_connector_run
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
            "connector_id": "confluence_space",
            "dataset_id": str(dataset_id),
            "config": {
                "base_url": "https://example.atlassian.net/wiki",
                "space_key": "DOCS",
                "auth": {"type": "bearer", "token": "secret-token"},
                "max_pages": 1,
            },
        },
    )
    assert res.status_code == 201, res.text
    body = res.json()
    cfg = body.get("config") or {}
    assert cfg.get("auth", {}).get("token") == "<redacted>"
    assert cfg.get("ingest_method") == "api_view"


def test_connectors_create_confluence_run_supports_include_attachments(monkeypatch):  # noqa: ANN001
    import app.api.v1.connectors as connectors_module
    from app.api.v1.connectors import create_connector_run
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
            "connector_id": "confluence_space",
            "dataset_id": str(dataset_id),
            "config": {
                "base_url": "https://example.atlassian.net/wiki",
                "space_key": "DOCS",
                "auth": {"type": "bearer", "token": "secret-token"},
                "include_attachments": True,
                "max_pages": 1,
            },
        },
    )
    assert res.status_code == 201, res.text
    body = res.json()
    cfg = body.get("config") or {}
    assert cfg.get("auth", {}).get("token") == "<redacted>"
    assert cfg.get("include_attachments") is True


def test_connectors_create_jira_run_redacts_auth_and_defaults_chunking(monkeypatch):  # noqa: ANN001
    import app.api.v1.connectors as connectors_module
    from app.api.v1.connectors import create_connector_run
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
            "connector_id": "jira_project",
            "dataset_id": str(dataset_id),
            "config": {
                "base_url": "https://example.atlassian.net",
                "project_key": "PLAT",
                "auth": {"type": "basic", "username": "bot@example.com", "password": "secret-token"},
                "max_issues": 1,
            },
        },
    )
    assert res.status_code == 201, res.text
    body = res.json()
    cfg = body.get("config") or {}
    assert body.get("connector_id") == "jira_project"
    assert cfg.get("auth", {}).get("password") == "<redacted>"
    assert cfg.get("chunk_strategy") == "jira_ticket"
    assert cfg.get("sync_mode") == "auto"


def test_connectors_create_jira_run_supports_attachment_options(monkeypatch):  # noqa: ANN001
    import app.api.v1.connectors as connectors_module
    from app.api.v1.connectors import create_connector_run
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
            "connector_id": "jira_project",
            "dataset_id": str(dataset_id),
            "config": {
                "base_url": "https://example.atlassian.net",
                "project_key": "PLAT",
                "include_attachments": True,
                "max_attachments_per_issue": 3,
                "max_total_attachments": 12,
            },
        },
    )
    assert res.status_code == 201, res.text
    body = res.json()
    cfg = body.get("config") or {}
    assert body.get("connector_id") == "jira_project"
    assert cfg.get("include_attachments") is True
    assert cfg.get("max_attachments_per_issue") == 3
    assert cfg.get("max_total_attachments") == 12


def test_connectors_accept_mysql_catalog_config(monkeypatch):  # noqa: ANN001
    import app.api.v1.connectors as connectors_module
    from app.api.v1.connectors import create_connector_run
    from app.core.config import settings

    # The current connector implementation gates all connector runs behind URL_INGEST_ENABLED.
    # MySQL catalog connector should not depend on URL egress, but we enable it here for the
    # pre-implementation failing test and keep it enabled after implementation for safety.
    monkeypatch.setattr(settings, "URL_INGEST_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "DB_CATALOG_ENABLED", True, raising=False)

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
            "connector_id": "mysql_catalog",
            "dataset_id": str(dataset_id),
            "config": {
                "host": "localhost",
                "port": 3306,
                "database": "demo",
                "username": "svc",
                "password": "secret",
                "row_sync_enabled": True,
                "row_sync_max_tables": 12,
                "row_sync_max_rows_per_table": 20,
                "row_sync_max_cols": 16,
            },
        },
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body.get("connector_id") == "mysql_catalog"
    assert body.get("dataset_id") == str(dataset_id)
    # Connector config secrets must be redacted in API responses.
    assert (body.get("config") or {}).get("password") == "<redacted>"
    assert (body.get("config") or {}).get("row_sync_enabled") is True
    assert (body.get("config") or {}).get("row_sync_max_tables") == 12
    assert (body.get("config") or {}).get("row_sync_max_rows_per_table") == 20
    assert (body.get("config") or {}).get("row_sync_max_cols") == 16


def test_connectors_accept_sqlserver_catalog_config(monkeypatch):  # noqa: ANN001
    import app.api.v1.connectors as connectors_module
    from app.api.v1.connectors import create_connector_run
    from app.core.config import settings

    monkeypatch.setattr(settings, "URL_INGEST_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "DB_CATALOG_ENABLED", True, raising=False)
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
            "connector_id": "sqlserver_catalog",
            "dataset_id": str(dataset_id),
            "config": {
                "host": "localhost",
                "port": 1433,
                "database": "demo",
                "username": "svc",
                "password": "secret",
                "row_sync_enabled": True,
                "row_sync_max_tables": 8,
                "row_sync_max_rows_per_table": 15,
                "row_sync_max_cols": 10,
            },
        },
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body.get("connector_id") == "sqlserver_catalog"
    assert body.get("dataset_id") == str(dataset_id)
    assert (body.get("config") or {}).get("password") == "<redacted>"
    assert (body.get("config") or {}).get("row_sync_enabled") is True
    assert (body.get("config") or {}).get("row_sync_max_tables") == 8
    assert (body.get("config") or {}).get("row_sync_max_rows_per_table") == 15
    assert (body.get("config") or {}).get("row_sync_max_cols") == 10


def test_connectors_runs_list_includes_acl_summary(monkeypatch):  # noqa: ANN001
    import app.api.v1.connectors as connectors_module
    from app.models.connector import ConnectorRun

    monkeypatch.setattr(connectors_module.DatasetService, "ensure_member", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(connectors_module.DatasetService, "get_dataset", lambda *_a, **_k: object(), raising=True)
    monkeypatch.setattr(connectors_module.DatasetService, "assert_dataset_writable", lambda *_a, **_k: None, raising=True)

    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    run_id = uuid.uuid4()

    class _DummyRunDoc:
        def __init__(self) -> None:
            self.document_id = uuid.uuid4()
            self.source_ref = "https://example.com/a.txt"
            self.status = "created"

    class _DummyRun:
        def __init__(self) -> None:
            self.id = run_id
            self.tenant_id = tenant_id
            self.dataset_id = dataset_id
            self.connector_id = "url_batch"
            self.requested_by = "test-account"
            self.status = "completed"
            self.config = {"urls": ["https://example.com/a.txt"], "access": {"mode": "partial_members"}}
            self.stats = {}
            self.error_message = None
            self.task_id = None
            self.created_at = datetime.now(UTC)
            self.started_at = self.created_at
            self.finished_at = self.created_at
            self.documents = [_DummyRunDoc()]

    dummy_run = _DummyRun()

    class _DummyQuery:
        def __init__(self, model):  # noqa: ANN001
            self.model = model

        def filter(self, *_a, **_k):  # noqa: ANN001
            return self

        def count(self) -> int:
            return 1

        def options(self, *_a, **_k):  # noqa: ANN001
            return self

        def order_by(self, *_a, **_k):  # noqa: ANN001
            return self

        def offset(self, *_a, **_k):  # noqa: ANN001
            return self

        def limit(self, *_a, **_k):  # noqa: ANN001
            return self

        def all(self):  # noqa: ANN001
            if self.model is ConnectorRun:
                return [dummy_run]
            return []

    class _DummyDB:
        def query(self, model):  # noqa: ANN001
            return _DummyQuery(model)

    dummy_db = _DummyDB()

    def _override_get_db():  # noqa: ANN202
        yield dummy_db

    def _override_get_tenant_id() -> uuid.UUID:
        return tenant_id

    def _override_get_current_account_id() -> str:
        return "test-account"

    monkeypatch.setattr(
        connectors_module,
        "_fetch_connector_run_acl_summaries",
        lambda *_a, **_k: {
            run_id: {
                "mode": "partial_members",
                "documents_total": 1,
                "access_mode_counts": {"partial_members": 1},
                "partial_members_doc_count": 1,
                "partial_member_count_min": 3,
                "partial_member_count_max": 3,
                "partial_group_count_min": 2,
                "partial_group_count_max": 2,
            }
        },
        raising=False,
    )

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = _override_get_tenant_id
    app.dependency_overrides[get_current_account_id] = _override_get_current_account_id
    app.include_router(connectors_module.router, prefix="/api/v1/connectors")
    client = TestClient(app)

    res = client.get(f"/api/v1/connectors/runs?dataset_id={dataset_id}&limit=20")
    assert res.status_code == 200, res.text
    body = res.json()
    assert (body.get("total") or 0) >= 1
    items = body.get("items") or []
    assert len(items) == 1
    assert (items[0].get("acl_summary") or {}).get("mode") == "partial_members"

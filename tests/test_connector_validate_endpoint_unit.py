from __future__ import annotations

import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.core.database import get_db
from tests.helpers.async_utils import yield_control


class _DummyDB:
    def add(self, _obj) -> None:  # noqa: ANN001
        return None

    def commit(self) -> None:
        return None

    def refresh(self, _obj) -> None:  # noqa: ANN001
        return None


def _override_get_db():  # noqa: ANN202
    yield _DummyDB()


def _override_get_tenant_id() -> uuid.UUID:
    return uuid.uuid4()


def _override_get_current_account_id() -> str:
    return "test-account"


def test_connectors_validate_endpoint_happy_path(monkeypatch):  # noqa: ANN001
    import app.api.v1.connectors_validation as connectors_module

    # Endpoint must exist.
    assert hasattr(connectors_module, "validate_connector_config")

    # Bypass membership checks for unit test.
    monkeypatch.setattr(connectors_module.DatasetService, "ensure_member", lambda *_a, **_k: None, raising=True)

    async def _ok_url(url: str) -> str:
        await yield_control()
        return url

    # Avoid DNS/network in unit tests; validate endpoint should be patchable.
    monkeypatch.setattr(connectors_module, "validate_url_for_ingest", _ok_url, raising=False)

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = _override_get_tenant_id
    app.dependency_overrides[get_current_account_id] = _override_get_current_account_id
    app.post("/api/v1/connectors/validate")(connectors_module.validate_connector_config)
    client = TestClient(app)

    res = client.post(
        "/api/v1/connectors/validate",
        json={
            "connector_id": "url_batch",
            "config": {"urls": ["https://example.com/a.txt"]},
            "check_connectivity": True,
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body.get("ok") is True
    assert body.get("connector_id") == "url_batch"
    assert isinstance(body.get("errors"), list) and not body.get("errors")
    assert (body.get("config") or {}).get("urls") == ["https://example.com/a.txt"]
    assert isinstance(body.get("checks"), dict)


def test_connectors_validate_redacts_password(monkeypatch):  # noqa: ANN001
    import app.api.v1.connectors_validation as connectors_module

    monkeypatch.setattr(connectors_module.DatasetService, "ensure_member", lambda *_a, **_k: None, raising=True)

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = _override_get_tenant_id
    app.dependency_overrides[get_current_account_id] = _override_get_current_account_id
    app.post("/api/v1/connectors/validate")(connectors_module.validate_connector_config)
    client = TestClient(app)

    res = client.post(
        "/api/v1/connectors/validate",
        json={
            "connector_id": "mysql_catalog",
            "config": {"host": "localhost", "port": 3306, "database": "demo", "username": "svc", "password": "secret"},
            "check_connectivity": False,
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body.get("ok") is True
    assert (body.get("config") or {}).get("password") == "<redacted>"


def test_connectors_validate_accepts_jira_config_and_redacts_password(monkeypatch):  # noqa: ANN001
    import app.api.v1.connectors_validation as connectors_module

    monkeypatch.setattr(connectors_module.DatasetService, "ensure_member", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(connectors_module, "_unknown_tenant_groups", lambda *_a, **_k: [], raising=True)

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = _override_get_tenant_id
    app.dependency_overrides[get_current_account_id] = _override_get_current_account_id
    app.post("/api/v1/connectors/validate")(connectors_module.validate_connector_config)
    client = TestClient(app)

    res = client.post(
        "/api/v1/connectors/validate",
        json={
            "connector_id": "jira_project",
            "config": {
                "base_url": "https://example.atlassian.net",
                "project_key": "PLAT",
                "auth": {"type": "basic", "username": "bot@example.com", "password": "secret"},
                "source_acl": {
                    "mode": "inherit",
                    "group_mappings": [
                        {
                            "source": {"system": "jira", "kind": "policy", "id": "security-level/10001"},
                            "group_id": str(uuid.uuid4()),
                        }
                    ],
                },
            },
            "check_connectivity": True,
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body.get("ok") is True
    assert (body.get("config") or {}).get("auth", {}).get("password") == "<redacted>"
    assert (body.get("config") or {}).get("chunk_strategy") == "jira_ticket"
    assert (body.get("checks") or {}).get("jira_project", {}).get("project_key") == "PLAT"


def test_connectors_validate_rejects_unknown_source_acl_groups(monkeypatch):  # noqa: ANN001
    import app.api.v1.connectors_validation as connectors_module

    # Bypass membership checks for unit test.
    monkeypatch.setattr(connectors_module.DatasetService, "ensure_member", lambda *_a, **_k: None, raising=True)

    async def _ok_url(url: str) -> str:
        await yield_control()
        return url

    monkeypatch.setattr(connectors_module, "validate_url_for_ingest", _ok_url, raising=False)

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
    app.post("/api/v1/connectors/validate")(connectors_module.validate_connector_config)
    client = TestClient(app)

    res = client.post(
        "/api/v1/connectors/validate",
        json={
            "connector_id": "url_batch",
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
            "check_connectivity": False,
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body.get("ok") is False
    errors = body.get("errors") or []
    assert any(e.get("loc") == ["source_acl", "group_mappings"] for e in errors), errors


def test_connectors_validate_rejects_unknown_access_groups(monkeypatch):  # noqa: ANN001
    import app.api.v1.connectors_validation as connectors_module

    monkeypatch.setattr(connectors_module.DatasetService, "ensure_member", lambda *_a, **_k: None, raising=True)

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
    app.post("/api/v1/connectors/validate")(connectors_module.validate_connector_config)
    client = TestClient(app)

    res = client.post(
        "/api/v1/connectors/validate",
        json={
            "connector_id": "url_batch",
            "config": {
                "urls": ["https://example.com/a.txt"],
                "access": {"mode": "partial_members", "partial_group_list": [str(missing_group_id)]},
            },
            "check_connectivity": False,
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body.get("ok") is False
    errors = body.get("errors") or []
    assert any(e.get("loc") == ["access", "partial_group_list"] for e in errors), errors

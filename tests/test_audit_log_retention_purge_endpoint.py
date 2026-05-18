from __future__ import annotations

import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.core.database import get_db
from app.services.dataset_service import DatasetService


class _DummyDB:
    def commit(self) -> None:
        return None


def _override_get_db():  # noqa: ANN202
    yield _DummyDB()


def _override_get_tenant_id() -> uuid.UUID:
    return uuid.uuid4()


def _override_get_current_account_id() -> str:
    return "test-account"


class _Member:
    def __init__(self, role: str):
        self.role = role


def test_audit_purge_denies_auditor_role(monkeypatch):  # noqa: ANN001
    from app.api.v1.audit import purge_audit_logs

    monkeypatch.setattr(DatasetService, "ensure_member", lambda *_a, **_k: _Member("auditor"), raising=True)

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = _override_get_tenant_id
    app.dependency_overrides[get_current_account_id] = _override_get_current_account_id
    app.post("/api/v1/audit/logs/purge")(purge_audit_logs)
    client = TestClient(app)

    res = client.post("/api/v1/audit/logs/purge?dry_run=true&retention_days=30")
    assert res.status_code == 403, res.text


def test_audit_purge_allows_admin_and_calls_service(monkeypatch):  # noqa: ANN001
    import app.api.v1.audit as audit_mod
    from app.api.v1.audit import purge_audit_logs

    monkeypatch.setattr(DatasetService, "ensure_member", lambda *_a, **_k: _Member("admin"), raising=True)

    called = {"plan": 0, "purge": 0}

    def _fake_plan(*_a, **_k):  # noqa: ANN001, ANN202
        called["plan"] += 1
        return 7

    def _fake_purge(*_a, **_k):  # noqa: ANN001, ANN202
        called["purge"] += 1
        return 3

    monkeypatch.setattr(audit_mod, "plan_audit_log_purge", _fake_plan, raising=True)
    monkeypatch.setattr(audit_mod, "purge_audit_log_rows", _fake_purge, raising=True)

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = _override_get_tenant_id
    app.dependency_overrides[get_current_account_id] = _override_get_current_account_id
    app.post("/api/v1/audit/logs/purge")(purge_audit_logs)
    client = TestClient(app)

    # Dry-run: should only plan.
    res0 = client.post("/api/v1/audit/logs/purge?dry_run=true&retention_days=30&max_delete=1000")
    assert res0.status_code == 200, res0.text
    body0 = res0.json()
    assert body0.get("dry_run") is True
    assert body0.get("scope") == "retention"
    assert body0.get("eligible") == 7
    assert body0.get("deleted") == 0
    assert called["plan"] == 1
    assert called["purge"] == 0

    # Real purge: should plan + purge.
    res1 = client.post("/api/v1/audit/logs/purge?dry_run=false&retention_days=30&max_delete=1000")
    assert res1.status_code == 200, res1.text
    body1 = res1.json()
    assert body1.get("dry_run") is False
    assert body1.get("scope") == "retention"
    assert body1.get("eligible") == 7
    assert body1.get("deleted") == 3
    assert called["plan"] == 2
    assert called["purge"] == 1


def test_audit_purge_filtered_requires_explicit_filter(monkeypatch):  # noqa: ANN001
    from app.api.v1.audit import purge_audit_logs

    monkeypatch.setattr(DatasetService, "ensure_member", lambda *_a, **_k: _Member("admin"), raising=True)

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = _override_get_tenant_id
    app.dependency_overrides[get_current_account_id] = _override_get_current_account_id
    app.post("/api/v1/audit/logs/purge")(purge_audit_logs)
    client = TestClient(app)

    res = client.post("/api/v1/audit/logs/purge?dry_run=true&purge_scope=filtered")
    assert res.status_code == 400, res.text
    assert "At least one filter" in res.text


def test_audit_purge_filtered_calls_filtered_service(monkeypatch):  # noqa: ANN001
    import app.api.v1.audit as audit_mod
    from app.api.v1.audit import purge_audit_logs

    monkeypatch.setattr(DatasetService, "ensure_member", lambda *_a, **_k: _Member("admin"), raising=True)

    called = {"plan": 0, "purge": 0}

    def _fake_plan(*_a, **kwargs):  # noqa: ANN001, ANN202
        called["plan"] += 1
        assert kwargs.get("action") == "audit.logs.purge"
        assert kwargs.get("max_delete") == 10
        return 5

    def _fake_purge(*_a, **kwargs):  # noqa: ANN001, ANN202
        called["purge"] += 1
        assert kwargs.get("action") == "audit.logs.purge"
        assert kwargs.get("max_delete") == 10
        return 2

    monkeypatch.setattr(audit_mod, "plan_filtered_audit_log_purge", _fake_plan, raising=True)
    monkeypatch.setattr(audit_mod, "purge_filtered_audit_log_rows", _fake_purge, raising=True)

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = _override_get_tenant_id
    app.dependency_overrides[get_current_account_id] = _override_get_current_account_id
    app.post("/api/v1/audit/logs/purge")(purge_audit_logs)
    client = TestClient(app)

    res0 = client.post(
        "/api/v1/audit/logs/purge?dry_run=true&purge_scope=filtered&action=audit.logs.purge&max_delete=10"
    )
    assert res0.status_code == 200, res0.text
    body0 = res0.json()
    assert body0.get("scope") == "filtered"
    assert body0.get("eligible") == 5
    assert body0.get("deleted") == 0
    assert body0.get("filters") == {"action": "audit.logs.purge"}
    assert called["plan"] == 1
    assert called["purge"] == 0

    res1 = client.post(
        "/api/v1/audit/logs/purge?dry_run=false&purge_scope=filtered&action=audit.logs.purge&max_delete=10"
    )
    assert res1.status_code == 200, res1.text
    body1 = res1.json()
    assert body1.get("scope") == "filtered"
    assert body1.get("eligible") == 5
    assert body1.get("deleted") == 2
    assert body1.get("filters") == {"action": "audit.logs.purge"}
    assert called["plan"] == 2
    assert called["purge"] == 1


def test_audit_delete_log_requires_manage_and_calls_service(monkeypatch):  # noqa: ANN001
    import app.api.v1.audit as audit_mod
    from app.api.v1.audit import delete_audit_log

    monkeypatch.setattr(DatasetService, "ensure_member", lambda *_a, **_k: _Member("admin"), raising=True)

    log_id = uuid.uuid4()
    called = {"delete": 0}

    def _fake_delete(*_a, **kwargs):  # noqa: ANN001, ANN202
        called["delete"] += 1
        assert kwargs.get("ids") == [log_id]
        return 1

    monkeypatch.setattr(audit_mod, "delete_audit_log_rows", _fake_delete, raising=True)

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = _override_get_tenant_id
    app.dependency_overrides[get_current_account_id] = _override_get_current_account_id
    app.delete("/api/v1/audit/logs/{log_id}")(delete_audit_log)
    client = TestClient(app)

    res = client.delete(f"/api/v1/audit/logs/{log_id}")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body.get("requested") == 1
    assert body.get("deleted") == 1
    assert body.get("missing") == 0
    assert body.get("ids") == [str(log_id)]
    assert called["delete"] == 1


def test_audit_bulk_delete_dedupes_ids_and_reports_missing(monkeypatch):  # noqa: ANN001
    import app.api.v1.audit as audit_mod
    from app.api.v1.audit import bulk_delete_audit_logs

    monkeypatch.setattr(DatasetService, "ensure_member", lambda *_a, **_k: _Member("admin"), raising=True)

    log_id_a = uuid.uuid4()
    log_id_b = uuid.uuid4()
    called = {"delete": 0}

    def _fake_delete(*_a, **kwargs):  # noqa: ANN001, ANN202
        called["delete"] += 1
        assert kwargs.get("ids") == [log_id_a, log_id_b]
        return 1

    monkeypatch.setattr(audit_mod, "delete_audit_log_rows", _fake_delete, raising=True)

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = _override_get_tenant_id
    app.dependency_overrides[get_current_account_id] = _override_get_current_account_id
    app.post("/api/v1/audit/logs/bulk-delete")(bulk_delete_audit_logs)
    client = TestClient(app)

    res = client.post(
        "/api/v1/audit/logs/bulk-delete",
        json={"ids": [str(log_id_a), str(log_id_b), str(log_id_a)]},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body.get("requested") == 2
    assert body.get("deleted") == 1
    assert body.get("missing") == 1
    assert body.get("ids") == [str(log_id_a), str(log_id_b)]
    assert called["delete"] == 1

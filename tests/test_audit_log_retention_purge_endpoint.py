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
    assert body0.get("eligible") == 7
    assert body0.get("deleted") == 0
    assert called["plan"] == 1
    assert called["purge"] == 0

    # Real purge: should plan + purge.
    res1 = client.post("/api/v1/audit/logs/purge?dry_run=false&retention_days=30&max_delete=1000")
    assert res1.status_code == 200, res1.text
    body1 = res1.json()
    assert body1.get("dry_run") is False
    assert body1.get("eligible") == 7
    assert body1.get("deleted") == 3
    assert called["plan"] == 2
    assert called["purge"] == 1


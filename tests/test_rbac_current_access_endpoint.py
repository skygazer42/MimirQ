
import uuid
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.core.database import get_db


class _DummyDB:
    pass


def _override_get_db():  # noqa: ANN202
    yield _DummyDB()


def _build_client(*, monkeypatch: pytest.MonkeyPatch, tenant_id: uuid.UUID, role: str) -> TestClient:
    import app.api.v1.rbac as rbac_api

    def _override_get_tenant_id() -> uuid.UUID:
        return tenant_id

    def _override_get_current_account_id() -> str:
        return "current-user"

    def _ensure_member(_db, requested_tenant_id, account_id):  # noqa: ANN001
        assert requested_tenant_id == tenant_id
        assert account_id == "current-user"
        return SimpleNamespace(role=role, is_active=True, is_current=True)

    monkeypatch.setattr(rbac_api.DatasetService, "ensure_member", _ensure_member, raising=True)

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = _override_get_tenant_id
    app.dependency_overrides[get_current_account_id] = _override_get_current_account_id
    app.include_router(rbac_api.router, prefix="/api/v1/rbac")
    return TestClient(app)


def test_rbac_me_exposes_current_member_permissions_without_admin_read(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id = uuid.uuid4()
    client = _build_client(monkeypatch=monkeypatch, tenant_id=tenant_id, role="auditor")

    res = client.get("/api/v1/rbac/me")
    assert res.status_code == 200, res.text
    body = res.json()

    assert body["tenant_id"] == str(tenant_id)
    assert body["account_id"] == "current-user"
    assert body["role"] == "auditor"
    assert body["permissions"] == ["audit.read", "table_sql.read"]
    assert body["is_active"] is True
    assert body["is_current"] is True


def test_rbac_me_owner_receives_admin_permissions(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id = uuid.uuid4()
    client = _build_client(monkeypatch=monkeypatch, tenant_id=tenant_id, role="owner")

    res = client.get("/api/v1/rbac/me")
    assert res.status_code == 200, res.text
    permissions = set(res.json()["permissions"])

    assert "settings.read" in permissions
    assert "observability.read" in permissions
    assert "usage.read" in permissions
    assert "audit.read" in permissions

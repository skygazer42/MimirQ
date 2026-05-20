from __future__ import annotations

import uuid
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.core.database import get_db


class _FakeQuery:
    def __init__(self, db: _FakeDB, model: object):
        self.db = db
        self.model_name = getattr(model, "__name__", str(model))

    def filter(self, *_args: object, **_kwargs: object) -> _FakeQuery:
        return self

    def first(self) -> object | None:
        if self.model_name == "TenantMember":
            return self.db.member
        return None

    def count(self) -> int:
        return self.db.other_admin_count

    def delete(self, synchronize_session: bool = False) -> int:  # noqa: FBT001, FBT002
        self.db.delete_calls.append(self.model_name)
        return self.db.delete_counts.get(self.model_name, 0)


class _FakeDB:
    def __init__(self, *, member: object | None, other_admin_count: int = 1):
        self.member = member
        self.other_admin_count = other_admin_count
        self.delete_counts = {
            "TenantGroupMember": 2,
            "DatasetPermission": 3,
            "DocumentPermission": 4,
        }
        self.delete_calls: list[str] = []
        self.deleted_member: object | None = None
        self.committed = False
        self.audit_events: list[dict[str, object]] = []

    def query(self, model: object) -> _FakeQuery:
        return _FakeQuery(self, model)

    def delete(self, item: object) -> None:
        self.deleted_member = item

    def commit(self) -> None:
        self.committed = True


def _build_client(
    monkeypatch,
    *,
    db: _FakeDB,
    tenant_id: uuid.UUID,
    account_id: str = "admin-user",
) -> TestClient:
    import app.api.v1.rbac as rbac_api

    def _override_get_db():  # noqa: ANN202
        yield db

    monkeypatch.setattr(
        rbac_api,
        "ensure_tenant_permission",
        lambda *_args, **_kwargs: SimpleNamespace(role="admin"),
        raising=True,
    )
    monkeypatch.setattr(
        rbac_api,
        "audit_log_event",
        lambda *_args, **kwargs: db.audit_events.append(kwargs),
        raising=True,
    )

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = lambda: tenant_id
    app.dependency_overrides[get_current_account_id] = lambda: account_id
    app.include_router(rbac_api.router, prefix="/api/v1/rbac")
    return TestClient(app)


def test_rbac_member_remove_deletes_membership_and_explicit_access(monkeypatch) -> None:  # noqa: ANN001
    tenant_id = uuid.uuid4()
    member = SimpleNamespace(user_id="alice", role="viewer", is_active=True, is_current=False)
    db = _FakeDB(member=member)
    client = _build_client(monkeypatch, db=db, tenant_id=tenant_id)

    res = client.delete("/api/v1/rbac/members/alice")

    assert res.status_code == 200, res.text
    assert res.json() == {
        "user_id": "alice",
        "removed": True,
        "revoked_group_memberships": 2,
        "revoked_dataset_permissions": 3,
        "revoked_document_permissions": 4,
    }
    assert db.deleted_member is member
    assert db.committed is True
    assert db.delete_calls == ["TenantGroupMember", "DatasetPermission", "DocumentPermission"]
    assert db.audit_events


def test_rbac_member_remove_rejects_current_user(monkeypatch) -> None:  # noqa: ANN001
    tenant_id = uuid.uuid4()
    member = SimpleNamespace(user_id="alice", role="admin", is_active=True, is_current=True)
    db = _FakeDB(member=member)
    client = _build_client(monkeypatch, db=db, tenant_id=tenant_id, account_id="alice")

    res = client.delete("/api/v1/rbac/members/alice")

    assert res.status_code == 409, res.text
    assert db.deleted_member is None
    assert db.committed is False


def test_rbac_member_remove_rejects_last_admin(monkeypatch) -> None:  # noqa: ANN001
    tenant_id = uuid.uuid4()
    member = SimpleNamespace(user_id="alice", role="admin", is_active=True, is_current=False)
    db = _FakeDB(member=member, other_admin_count=0)
    client = _build_client(monkeypatch, db=db, tenant_id=tenant_id)

    res = client.delete("/api/v1/rbac/members/alice")

    assert res.status_code == 409, res.text
    assert db.deleted_member is None
    assert db.committed is False

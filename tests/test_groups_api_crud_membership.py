from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.core.database import get_db


class _DummyDB:
    def commit(self) -> None:
        return None


def _override_get_db():  # noqa: ANN202
    yield _DummyDB()


def _build_client(*, monkeypatch: pytest.MonkeyPatch, tenant_id: uuid.UUID, allowed_permissions: set[str], store):  # noqa: ANN001
    import app.api.v1.groups as groups_api

    def _override_get_tenant_id() -> uuid.UUID:
        return tenant_id

    current_account_id = {"value": "test-admin"}

    def _override_get_current_account_id() -> str:
        return current_account_id["value"]

    def _ensure(_db, _tenant_id, _account_id, perm, detail: str | None = None):  # noqa: ANN001
        key = str(perm or "")
        if key not in allowed_permissions:
            raise HTTPException(status_code=403, detail=detail or "forbidden")

    monkeypatch.setattr(groups_api, "ensure_tenant_permission", _ensure, raising=True)
    monkeypatch.setattr(groups_api, "audit_log_event", lambda *_a, **_k: None, raising=False)

    # In-memory service stubs.
    def _list_groups(_db, *, tenant_id: uuid.UUID, skip: int = 0, limit: int = 200):  # noqa: ANN001
        items = [g for g in store["groups"].values() if g.tenant_id == tenant_id]
        items.sort(key=lambda g: str(getattr(g, "name", "") or "").lower())
        sliced = items[max(0, int(skip or 0)) : max(0, int(skip or 0)) + max(1, int(limit or 0))]
        return len(items), sliced

    def _create_group(_db, *, tenant_id: uuid.UUID, name: str, external_id: str | None = None):  # noqa: ANN001
        # Ensure request schema normalization ran (trim + required).
        assert name == name.strip()
        assert name, "expected non-empty name after validation"
        if external_id is not None:
            assert external_id == external_id.strip()

        # Enforce name uniqueness within tenant.
        for g in store["groups"].values():
            if g.tenant_id == tenant_id and str(g.name) == str(name):
                raise HTTPException(status_code=409, detail="Group name already exists")

        gid = uuid.uuid4()
        now = datetime.now(timezone.utc)
        obj = SimpleNamespace(
            id=gid,
            tenant_id=tenant_id,
            name=name,
            external_id=external_id,
            created_at=now,
            updated_at=None,
        )
        store["groups"][gid] = obj
        store["members"].setdefault(gid, {})
        return obj

    def _get_group(_db, *, tenant_id: uuid.UUID, group_id: uuid.UUID):  # noqa: ANN001
        g = store["groups"].get(group_id)
        if not g or g.tenant_id != tenant_id:
            raise HTTPException(status_code=404, detail="Group not found")
        return g

    def _update_group(  # noqa: ANN001
        _db,
        *,
        tenant_id: uuid.UUID,
        group_id: uuid.UUID,
        name: str | None,
        external_id: str | None,
    ):
        g = _get_group(_db, tenant_id=tenant_id, group_id=group_id)
        if name is not None:
            assert name == name.strip()
            assert name
            for other in store["groups"].values():
                if other.tenant_id == tenant_id and other.id != group_id and str(other.name) == str(name):
                    raise HTTPException(status_code=409, detail="Group name already exists")
            g.name = name
        if external_id is not None:
            g.external_id = external_id
        g.updated_at = datetime.now(timezone.utc)
        return g

    def _delete_group(_db, *, tenant_id: uuid.UUID, group_id: uuid.UUID):  # noqa: ANN001
        _get_group(_db, tenant_id=tenant_id, group_id=group_id)
        store["groups"].pop(group_id, None)
        store["members"].pop(group_id, None)

    def _list_members(_db, *, tenant_id: uuid.UUID, group_id: uuid.UUID, skip: int = 0, limit: int = 500):  # noqa: ANN001
        _get_group(_db, tenant_id=tenant_id, group_id=group_id)
        items = [
            SimpleNamespace(user_id=uid, created_at=created_at)
            for uid, created_at in (store["members"].get(group_id, {}) or {}).items()
        ]
        items.sort(key=lambda m: m.created_at, reverse=True)
        sliced = items[max(0, int(skip or 0)) : max(0, int(skip or 0)) + max(1, int(limit or 0))]
        return len(items), sliced

    def _add_members(_db, *, tenant_id: uuid.UUID, group_id: uuid.UUID, member_ids: list[str]):  # noqa: ANN001
        _get_group(_db, tenant_id=tenant_id, group_id=group_id)
        # Ensure request schema normalization ran (trim/dedupe/max 200).
        assert member_ids == list(dict.fromkeys(member_ids))
        for mid in member_ids:
            assert mid == mid.strip()
            assert 0 < len(mid) <= 255

        allowed_members = set(store["tenant_members"])
        missing = [m for m in member_ids if m not in allowed_members]
        if missing:
            raise HTTPException(status_code=400, detail=f"Unknown tenant members: {', '.join(missing[:20])}")

        now = datetime.now(timezone.utc)
        members = store["members"].setdefault(group_id, {})
        added = 0
        for mid in member_ids:
            if mid in members:
                continue
            members[mid] = now
            added += 1
        return added

    def _remove_members(_db, *, tenant_id: uuid.UUID, group_id: uuid.UUID, member_ids: list[str]):  # noqa: ANN001
        _get_group(_db, tenant_id=tenant_id, group_id=group_id)
        members = store["members"].setdefault(group_id, {})
        removed = 0
        for mid in member_ids:
            if mid in members:
                members.pop(mid, None)
                removed += 1
        return removed

    monkeypatch.setattr(groups_api.TenantGroupService, "list_groups", _list_groups, raising=True)
    monkeypatch.setattr(groups_api.TenantGroupService, "create_group", _create_group, raising=True)
    monkeypatch.setattr(groups_api.TenantGroupService, "get_group", _get_group, raising=True)
    monkeypatch.setattr(groups_api.TenantGroupService, "update_group", _update_group, raising=True)
    monkeypatch.setattr(groups_api.TenantGroupService, "delete_group", _delete_group, raising=True)
    monkeypatch.setattr(groups_api.TenantGroupService, "list_members", _list_members, raising=True)
    monkeypatch.setattr(groups_api.TenantGroupService, "add_members", _add_members, raising=True)
    monkeypatch.setattr(groups_api.TenantGroupService, "remove_members", _remove_members, raising=True)

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = _override_get_tenant_id
    app.dependency_overrides[get_current_account_id] = _override_get_current_account_id
    app.include_router(groups_api.router, prefix="/api/v1/groups")
    return TestClient(app), current_account_id


def test_groups_api_crud_and_membership_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id = uuid.uuid4()
    store = {
        "groups": {},
        "members": {},
        "tenant_members": {"alice", "bob", "charlie"},
    }
    client, _current_account_id = _build_client(
        monkeypatch=monkeypatch,
        tenant_id=tenant_id,
        allowed_permissions={"settings.read", "settings.write"},
        store=store,
    )

    res = client.get("/api/v1/groups?limit=50")
    assert res.status_code == 200, res.text
    assert res.json() == {"total": 0, "items": []}

    res = client.post("/api/v1/groups", json={"name": "  engineering  ", "external_id": "  "})
    assert res.status_code == 201, res.text
    created = res.json()
    assert created.get("name") == "engineering"
    assert created.get("external_id") is None
    group_id = created.get("id")
    assert group_id

    res = client.get("/api/v1/groups")
    assert res.status_code == 200, res.text
    listed = res.json()
    assert listed.get("total") == 1
    assert len(listed.get("items") or []) == 1

    res = client.get(f"/api/v1/groups/{group_id}")
    assert res.status_code == 200, res.text
    assert res.json().get("id") == group_id

    res = client.patch(f"/api/v1/groups/{group_id}", json={"external_id": "ext-1"})
    assert res.status_code == 200, res.text
    assert res.json().get("external_id") == "ext-1"

    res = client.post(f"/api/v1/groups/{group_id}/members", json={"member_ids": [" alice ", "bob", "alice"]})
    assert res.status_code == 200, res.text
    assert res.json().get("updated") == 2

    res = client.get(f"/api/v1/groups/{group_id}/members")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body.get("total") == 2
    ids = sorted([it.get("user_id") for it in (body.get("items") or [])])
    assert ids == ["alice", "bob"]

    res = client.post(f"/api/v1/groups/{group_id}/members/remove", json={"member_ids": ["bob"]})
    assert res.status_code == 200, res.text
    assert res.json().get("updated") == 1

    res = client.delete(f"/api/v1/groups/{group_id}")
    assert res.status_code == 204, res.text

    res = client.get("/api/v1/groups")
    assert res.status_code == 200, res.text
    assert res.json().get("total") == 0


def test_groups_api_enforces_read_vs_write_permissions(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id = uuid.uuid4()
    store = {"groups": {}, "members": {}, "tenant_members": {"alice"}}
    client, _current_account_id = _build_client(
        monkeypatch=monkeypatch,
        tenant_id=tenant_id,
        allowed_permissions={"settings.read"},  # no write
        store=store,
    )

    res = client.get("/api/v1/groups")
    assert res.status_code == 200, res.text

    res = client.post("/api/v1/groups", json={"name": "engineering"})
    assert res.status_code == 403, res.text


def test_groups_api_validates_inputs(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id = uuid.uuid4()
    store = {"groups": {}, "members": {}, "tenant_members": {"alice"}}
    client, _current_account_id = _build_client(
        monkeypatch=monkeypatch,
        tenant_id=tenant_id,
        allowed_permissions={"settings.read", "settings.write"},
        store=store,
    )

    res = client.post("/api/v1/groups", json={"name": ""})
    assert res.status_code == 422, res.text

    res = client.post("/api/v1/groups", json={"name": "x" * 256})
    assert res.status_code == 422, res.text

    res = client.get("/api/v1/groups/invalid-uuid")
    assert res.status_code == 422, res.text

    group_id = str(uuid.uuid4())
    res = client.post(f"/api/v1/groups/{group_id}/members", json={"member_ids": ["x" * 256]})
    assert res.status_code == 422, res.text

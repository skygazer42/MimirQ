from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies.tenant import get_tenant_id
from app.core.database import get_db


class _DummyDB:
    def commit(self) -> None:
        return None


def _override_get_db():  # noqa: ANN202
    yield _DummyDB()


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_scim_discovery_endpoints_return_valid_scim_json(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.api.v1.scim as scim_api

    token = "scim-test-token"
    monkeypatch.setattr(scim_api.settings, "SCIM_ENABLED", True, raising=False)
    monkeypatch.setattr(scim_api.settings, "SCIM_BEARER_TOKEN", token, raising=False)
    monkeypatch.setattr(scim_api.settings, "SCIM_PATCH_GROUP_MEMBERSHIP_ENABLED", False, raising=False)

    tenant_id = uuid.uuid4()

    def _override_get_tenant_id(_request=None):  # noqa: ANN001, ANN202
        return tenant_id

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = _override_get_tenant_id
    app.include_router(scim_api.router, prefix="/api/v1/scim/v2")
    client = TestClient(app)

    res = client.get("/api/v1/scim/v2/ServiceProviderConfig", headers=_auth(token))
    assert res.status_code == 200, res.text
    body = res.json()
    assert "schemas" in body
    assert body.get("patch", {}).get("supported") is False

    res = client.get("/api/v1/scim/v2/Schemas", headers=_auth(token))
    assert res.status_code == 200, res.text
    body = res.json()
    assert body.get("schemas") == ["urn:ietf:params:scim:api:messages:2.0:ListResponse"]
    assert isinstance(body.get("Resources"), list)


def test_scim_groups_list_get_pagination_and_tenant_isolation(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.api.v1.scim as scim_api

    token = "scim-test-token"
    monkeypatch.setattr(scim_api.settings, "SCIM_ENABLED", True, raising=False)
    monkeypatch.setattr(scim_api.settings, "SCIM_BEARER_TOKEN", token, raising=False)

    tenant_a = uuid.uuid4()
    tenant_b = uuid.uuid4()

    now = datetime.now(timezone.utc)
    g1 = SimpleNamespace(id=uuid.uuid4(), tenant_id=tenant_a, name="engineering", external_id=None, created_at=now, updated_at=now)
    g2 = SimpleNamespace(id=uuid.uuid4(), tenant_id=tenant_a, name="finance", external_id="ext-1", created_at=now, updated_at=now)
    g_other = SimpleNamespace(id=uuid.uuid4(), tenant_id=tenant_b, name="other", external_id=None, created_at=now, updated_at=now)

    store = {"groups": [g1, g2, g_other], "members": {g1.id: ["alice"], g2.id: []}}

    tenant_ctx = {"value": tenant_a}

    def _override_get_tenant_id(_request=None):  # noqa: ANN001, ANN202
        return tenant_ctx["value"]

    def _list_groups(_db, *, tenant_id, skip=0, limit=200):  # noqa: ANN001
        items = [g for g in store["groups"] if g.tenant_id == tenant_id]
        items.sort(key=lambda x: str(getattr(x, "name", "") or "").lower())
        sliced = items[max(0, int(skip or 0)) : max(0, int(skip or 0)) + max(1, int(limit or 0))]
        return len(items), sliced

    def _get_group(_db, *, tenant_id, group_id):  # noqa: ANN001
        for g in store["groups"]:
            if g.id == group_id and g.tenant_id == tenant_id:
                return g
        raise scim_api.HTTPException(status_code=404, detail="Group not found")

    def _list_members(_db, *, tenant_id, group_id, skip=0, limit=2000):  # noqa: ANN001
        _get_group(_db, tenant_id=tenant_id, group_id=group_id)
        members = list(store["members"].get(group_id, []))
        members = members[max(0, int(skip or 0)) : max(0, int(skip or 0)) + max(1, int(limit or 0))]
        rows = [SimpleNamespace(user_id=m, created_at=now) for m in members]
        return len(store["members"].get(group_id, [])), rows

    monkeypatch.setattr(scim_api.TenantGroupService, "list_groups", _list_groups, raising=True)
    monkeypatch.setattr(scim_api.TenantGroupService, "get_group", _get_group, raising=True)
    monkeypatch.setattr(scim_api.TenantGroupService, "list_members", _list_members, raising=True)

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = _override_get_tenant_id
    app.include_router(scim_api.router, prefix="/api/v1/scim/v2")
    client = TestClient(app)

    res = client.get("/api/v1/scim/v2/Groups?startIndex=1&count=1", headers=_auth(token))
    assert res.status_code == 200, res.text
    body = res.json()
    assert body.get("totalResults") == 2
    assert body.get("startIndex") == 1
    assert body.get("itemsPerPage") == 1
    assert len(body.get("Resources") or []) == 1

    res = client.get("/api/v1/scim/v2/Groups?startIndex=2&count=1", headers=_auth(token))
    assert res.status_code == 200, res.text
    body2 = res.json()
    assert body2.get("totalResults") == 2
    assert len(body2.get("Resources") or []) == 1

    # Tenant isolation: switching tenant should not see tenant_a groups.
    tenant_ctx["value"] = tenant_b
    res = client.get("/api/v1/scim/v2/Groups", headers=_auth(token))
    assert res.status_code == 200, res.text
    body3 = res.json()
    assert body3.get("totalResults") == 1
    assert (body3.get("Resources") or [])[0].get("displayName") == "other"


def test_scim_users_list_get_and_patch_group_membership(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.api.v1.scim as scim_api

    token = "scim-test-token"
    monkeypatch.setattr(scim_api.settings, "SCIM_ENABLED", True, raising=False)
    monkeypatch.setattr(scim_api.settings, "SCIM_BEARER_TOKEN", token, raising=False)
    monkeypatch.setattr(scim_api.settings, "SCIM_PATCH_GROUP_MEMBERSHIP_ENABLED", True, raising=False)

    tenant_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    users = [
        SimpleNamespace(tenant_id=tenant_id, user_id="alice", is_current=True, created_at=now, updated_at=now),
        SimpleNamespace(tenant_id=tenant_id, user_id="bob", is_current=False, created_at=now, updated_at=now),
    ]

    group = SimpleNamespace(id=uuid.uuid4(), tenant_id=tenant_id, name="engineering", external_id=None, created_at=now, updated_at=now)
    members = {group.id: {"alice"}}

    def _override_get_tenant_id(_request=None):  # noqa: ANN001, ANN202
        return tenant_id

    def _list_users(_db, *, tenant_id, skip, limit):  # noqa: ANN001
        items = [u for u in users if u.tenant_id == tenant_id]
        items.sort(key=lambda x: str(x.user_id))
        sliced = items[max(0, int(skip or 0)) : max(0, int(skip or 0)) + max(1, int(limit or 0))]
        return len(items), sliced

    def _get_user(_db, *, tenant_id, user_id):  # noqa: ANN001
        for u in users:
            if u.tenant_id == tenant_id and u.user_id == user_id:
                return u
        return None

    monkeypatch.setattr(scim_api, "_list_users", _list_users, raising=True)
    monkeypatch.setattr(scim_api, "_get_user", _get_user, raising=True)

    def _get_group(_db, *, tenant_id, group_id):  # noqa: ANN001
        if group.tenant_id == tenant_id and group.id == group_id:
            return group
        raise scim_api.HTTPException(status_code=404, detail="Group not found")

    def _list_members(_db, *, tenant_id, group_id, skip=0, limit=2000):  # noqa: ANN001
        _get_group(_db, tenant_id=tenant_id, group_id=group_id)
        ids = sorted(list(members.get(group_id, set())))
        ids = ids[max(0, int(skip or 0)) : max(0, int(skip or 0)) + max(1, int(limit or 0))]
        rows = [SimpleNamespace(user_id=uid, created_at=now) for uid in ids]
        return len(members.get(group_id, set())), rows

    def _add_members(_db, *, tenant_id, group_id, member_ids):  # noqa: ANN001
        _get_group(_db, tenant_id=tenant_id, group_id=group_id)
        current = members.setdefault(group_id, set())
        before = set(current)
        for uid in member_ids:
            current.add(str(uid))
        return len(current - before)

    def _remove_members(_db, *, tenant_id, group_id, member_ids):  # noqa: ANN001
        _get_group(_db, tenant_id=tenant_id, group_id=group_id)
        current = members.setdefault(group_id, set())
        before = set(current)
        for uid in member_ids:
            current.discard(str(uid))
        return len(before - current)

    monkeypatch.setattr(scim_api.TenantGroupService, "get_group", _get_group, raising=True)
    monkeypatch.setattr(scim_api.TenantGroupService, "list_members", _list_members, raising=True)
    monkeypatch.setattr(scim_api.TenantGroupService, "add_members", _add_members, raising=True)
    monkeypatch.setattr(scim_api.TenantGroupService, "remove_members", _remove_members, raising=True)

    called = {"audit": 0}
    monkeypatch.setattr(scim_api, "audit_log_event", lambda *_a, **_k: called.__setitem__("audit", called["audit"] + 1), raising=True)

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = _override_get_tenant_id
    app.include_router(scim_api.router, prefix="/api/v1/scim/v2")
    client = TestClient(app)

    res = client.get("/api/v1/scim/v2/Users?startIndex=1&count=50", headers=_auth(token))
    assert res.status_code == 200, res.text
    body = res.json()
    assert body.get("totalResults") == 2
    assert [r.get("id") for r in (body.get("Resources") or [])] == ["alice", "bob"]

    res = client.get("/api/v1/scim/v2/Users/alice", headers=_auth(token))
    assert res.status_code == 200, res.text
    assert res.json().get("userName") == "alice"

    res = client.patch(
        f"/api/v1/scim/v2/Groups/{group.id}",
        headers=_auth(token),
        json={
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
            "Operations": [
                {"op": "Add", "path": "members", "value": [{"value": "bob"}]},
                {"op": "Remove", "path": 'members[value eq \"alice\"]'},
            ],
        },
    )
    assert res.status_code == 200, res.text
    patched = res.json()
    patched_members = sorted([m.get("value") for m in (patched.get("members") or [])])
    assert patched_members == ["bob"]
    assert called["audit"] == 1


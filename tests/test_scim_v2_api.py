from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies.tenant import get_tenant_id
from app.core.database import get_db


class _DummyDB:
    def __init__(self) -> None:
        self.added: list[object] = []

    def add(self, item: object) -> None:
        self.added.append(item)

    def commit(self) -> None:
        return None

    def refresh(self, _item: object) -> None:
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

    now = datetime.now(UTC)
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
    now = datetime.now(UTC)

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
        ids = sorted(members.get(group_id, set()))
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


def test_scim_bearer_token_rotation_and_sha256(monkeypatch: pytest.MonkeyPatch) -> None:
    import hashlib

    import app.api.v1.scim as scim_api

    monkeypatch.setattr(scim_api.settings, "SCIM_ENABLED", True, raising=False)
    monkeypatch.setattr(scim_api.settings, "SCIM_PATCH_GROUP_MEMBERSHIP_ENABLED", False, raising=False)

    tenant_id = uuid.uuid4()

    def _override_get_tenant_id(_request=None):  # noqa: ANN001, ANN202
        return tenant_id

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = _override_get_tenant_id
    app.include_router(scim_api.router, prefix="/api/v1/scim/v2")
    client = TestClient(app)

    # Rotation: accept any token in the active set.
    monkeypatch.setattr(scim_api.settings, "SCIM_BEARER_TOKEN", "tok_a, tok_b", raising=False)
    assert client.get("/api/v1/scim/v2/ServiceProviderConfig", headers=_auth("tok_a")).status_code == 200
    assert client.get("/api/v1/scim/v2/ServiceProviderConfig", headers=_auth("tok_b")).status_code == 200
    assert client.get("/api/v1/scim/v2/ServiceProviderConfig", headers=_auth("wrong")).status_code == 401

    # Hashed token storage: config holds sha256 digest; client still sends raw.
    raw = "super-secret-scim-token"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    monkeypatch.setattr(scim_api.settings, "SCIM_BEARER_TOKEN", f"sha256:{digest}", raising=False)
    assert client.get("/api/v1/scim/v2/ServiceProviderConfig", headers=_auth(raw)).status_code == 200
    assert client.get("/api/v1/scim/v2/ServiceProviderConfig", headers=_auth("wrong")).status_code == 401


def test_scim_ip_allowlist_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.api.v1.scim as scim_api

    token = "scim-test-token"
    monkeypatch.setattr(scim_api.settings, "SCIM_ENABLED", True, raising=False)
    monkeypatch.setattr(scim_api.settings, "SCIM_BEARER_TOKEN", token, raising=False)
    monkeypatch.setattr(scim_api.settings, "SCIM_IP_ALLOWLIST_CIDRS", "127.0.0.1/32", raising=False)

    tenant_id = uuid.uuid4()

    def _override_get_tenant_id(_request=None):  # noqa: ANN001, ANN202
        return tenant_id

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = _override_get_tenant_id
    app.include_router(scim_api.router, prefix="/api/v1/scim/v2")
    client = TestClient(app)

    # No XFF/X-Real-IP in TestClient => request.client.host is not an IP => deny.
    res = client.get("/api/v1/scim/v2/ServiceProviderConfig", headers=_auth(token))
    assert res.status_code == 403

    res = client.get(
        "/api/v1/scim/v2/ServiceProviderConfig",
        headers={**_auth(token), "X-Forwarded-For": "127.0.0.1"},
    )
    assert res.status_code == 200, res.text

    res = client.get(
        "/api/v1/scim/v2/ServiceProviderConfig",
        headers={**_auth(token), "X-Forwarded-For": "10.0.0.1"},
    )
    assert res.status_code == 403


def test_scim_users_create_and_patch_active(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.api.v1.scim as scim_api

    token = "scim-test-token"
    monkeypatch.setattr(scim_api.settings, "SCIM_ENABLED", True, raising=False)
    monkeypatch.setattr(scim_api.settings, "SCIM_BEARER_TOKEN", token, raising=False)
    monkeypatch.setattr(scim_api.settings, "SCIM_USERS_CREATE_ENABLED", True, raising=False)
    monkeypatch.setattr(scim_api.settings, "SCIM_USERS_PATCH_ACTIVE_ENABLED", True, raising=False)

    tenant_id = uuid.uuid4()
    now = datetime.now(UTC)

    store: dict[str, SimpleNamespace] = {}

    def _override_get_tenant_id(_request=None):  # noqa: ANN001, ANN202
        return tenant_id

    def _get_user(_db, *, tenant_id, user_id):  # noqa: ANN001
        return store.get(str(user_id))

    monkeypatch.setattr(scim_api, "_get_user", _get_user, raising=True)

    def _member_ctor(**kwargs):  # noqa: ANN001, ANN202
        return SimpleNamespace(created_at=now, updated_at=now, **kwargs)

    monkeypatch.setattr(scim_api, "TenantMember", _member_ctor, raising=True)

    called = {"audit": 0}
    monkeypatch.setattr(scim_api, "audit_log_event", lambda *_a, **_k: called.__setitem__("audit", called["audit"] + 1), raising=True)

    db = _DummyDB()

    def _override_get_db_local():  # noqa: ANN202
        yield db

    # Capture created members via db.add.
    def _add(item: object) -> None:
        db.added.append(item)
        if isinstance(item, SimpleNamespace) and getattr(item, "user_id", None):
            store[str(item.user_id)] = item

    db.add = _add  # type: ignore[method-assign]

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db_local
    app.dependency_overrides[get_tenant_id] = _override_get_tenant_id
    app.include_router(scim_api.router, prefix="/api/v1/scim/v2")
    client = TestClient(app)

    res = client.post(
        "/api/v1/scim/v2/Users",
        headers=_auth(token),
        json={"schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"], "userName": "alice", "active": True},
    )
    assert res.status_code == 201, res.text
    assert res.json().get("id") == "alice"
    assert res.json().get("active") is True

    # Create again => uniqueness.
    res = client.post(
        "/api/v1/scim/v2/Users",
        headers=_auth(token),
        json={"schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"], "userName": "alice", "active": True},
    )
    assert res.status_code == 409, res.text
    assert res.json().get("scimType") == "uniqueness"

    res = client.patch(
        "/api/v1/scim/v2/Users/alice",
        headers=_auth(token),
        json={
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
            "Operations": [{"op": "Replace", "path": "active", "value": False}],
        },
    )
    assert res.status_code == 200, res.text
    assert res.json().get("active") is False
    assert called["audit"] >= 2


def test_scim_deprovision_policy_revokes_group_memberships(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.api.v1.scim as scim_api

    token = "scim-test-token"
    monkeypatch.setattr(scim_api.settings, "SCIM_ENABLED", True, raising=False)
    monkeypatch.setattr(scim_api.settings, "SCIM_BEARER_TOKEN", token, raising=False)
    monkeypatch.setattr(scim_api.settings, "SCIM_USERS_PATCH_ACTIVE_ENABLED", True, raising=False)
    monkeypatch.setattr(scim_api.settings, "SCIM_DEPROVISION_REVOKE_GROUP_MEMBERSHIPS_ENABLED", True, raising=False)

    tenant_id = uuid.uuid4()
    now = datetime.now(UTC)

    user = SimpleNamespace(tenant_id=tenant_id, user_id="alice", is_active=True, is_current=False, created_at=now, updated_at=now)

    def _override_get_tenant_id(_request=None):  # noqa: ANN001, ANN202
        return tenant_id

    def _get_user(_db, *, tenant_id, user_id):  # noqa: ANN001
        return user if str(user_id) == "alice" else None

    monkeypatch.setattr(scim_api, "_get_user", _get_user, raising=True)

    called = {"audit": 0, "revoke": 0}
    monkeypatch.setattr(scim_api, "audit_log_event", lambda *_a, **_k: called.__setitem__("audit", called["audit"] + 1), raising=True)

    def _revoke(_db, *, tenant_id, user_id):  # noqa: ANN001
        called["revoke"] += 1
        assert str(user_id) == "alice"
        return 3

    monkeypatch.setattr(scim_api, "_revoke_group_memberships_for_user", _revoke, raising=True)

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = _override_get_tenant_id
    app.include_router(scim_api.router, prefix="/api/v1/scim/v2")
    client = TestClient(app)

    res = client.patch(
        "/api/v1/scim/v2/Users/alice",
        headers=_auth(token),
        json={
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
            "Operations": [{"op": "Replace", "path": "active", "value": False}],
        },
    )
    assert res.status_code == 200, res.text
    assert res.json().get("active") is False
    assert called["revoke"] == 1
    assert called["audit"] >= 1


def test_scim_groups_create_put_delete_and_external_id_uniqueness(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.api.v1.scim as scim_api

    token = "scim-test-token"
    monkeypatch.setattr(scim_api.settings, "SCIM_ENABLED", True, raising=False)
    monkeypatch.setattr(scim_api.settings, "SCIM_BEARER_TOKEN", token, raising=False)
    monkeypatch.setattr(scim_api.settings, "SCIM_GROUPS_MUTATION_ENABLED", True, raising=False)

    tenant_id = uuid.uuid4()
    now = datetime.now(UTC)

    groups: dict[uuid.UUID, SimpleNamespace] = {}

    def _override_get_tenant_id(_request=None):  # noqa: ANN001, ANN202
        return tenant_id

    def _create_group(_db, *, tenant_id, name, external_id=None):  # noqa: ANN001
        if external_id and any(g.external_id == external_id for g in groups.values()):
            raise scim_api.HTTPException(status_code=409, detail="Group external_id already exists")
        gid = uuid.uuid4()
        g = SimpleNamespace(id=gid, tenant_id=tenant_id, name=str(name), external_id=external_id, created_at=now, updated_at=now)
        groups[gid] = g
        return g

    def _update_group(_db, *, tenant_id, group_id, name, external_id):  # noqa: ANN001
        g = groups.get(group_id)
        if not g or g.tenant_id != tenant_id:
            raise scim_api.HTTPException(status_code=404, detail="Group not found")
        if external_id is not None and external_id and any((og.id != group_id and og.external_id == external_id) for og in groups.values()):
            raise scim_api.HTTPException(status_code=409, detail="Group external_id already exists")
        g.name = str(name)
        if external_id is not None:
            g.external_id = external_id or None
        g.updated_at = now
        return g

    def _get_group(_db, *, tenant_id, group_id):  # noqa: ANN001
        g = groups.get(group_id)
        if not g or g.tenant_id != tenant_id:
            raise scim_api.HTTPException(status_code=404, detail="Group not found")
        return g

    def _delete_group(_db, *, tenant_id, group_id):  # noqa: ANN001
        _get_group(_db, tenant_id=tenant_id, group_id=group_id)
        groups.pop(group_id, None)

    monkeypatch.setattr(scim_api.TenantGroupService, "create_group", _create_group, raising=True)
    monkeypatch.setattr(scim_api.TenantGroupService, "update_group", _update_group, raising=True)
    monkeypatch.setattr(scim_api.TenantGroupService, "get_group", _get_group, raising=True)
    monkeypatch.setattr(scim_api.TenantGroupService, "delete_group", _delete_group, raising=True)

    called = {"audit": 0}
    monkeypatch.setattr(scim_api, "audit_log_event", lambda *_a, **_k: called.__setitem__("audit", called["audit"] + 1), raising=True)

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = _override_get_tenant_id
    app.include_router(scim_api.router, prefix="/api/v1/scim/v2")
    client = TestClient(app)

    res = client.post(
        "/api/v1/scim/v2/Groups",
        headers=_auth(token),
        json={"schemas": ["urn:ietf:params:scim:schemas:core:2.0:Group"], "displayName": "engineering", "externalId": "ext-1"},
    )
    assert res.status_code == 201, res.text
    group_id = uuid.UUID(res.json().get("id"))

    # externalId uniqueness => 409 + scimType=uniqueness
    res = client.post(
        "/api/v1/scim/v2/Groups",
        headers=_auth(token),
        json={"schemas": ["urn:ietf:params:scim:schemas:core:2.0:Group"], "displayName": "eng2", "externalId": "ext-1"},
    )
    assert res.status_code == 409, res.text
    assert res.json().get("scimType") == "uniqueness"

    res = client.put(
        f"/api/v1/scim/v2/Groups/{group_id}",
        headers=_auth(token),
        json={"schemas": ["urn:ietf:params:scim:schemas:core:2.0:Group"], "displayName": "engineering-renamed"},
    )
    assert res.status_code == 200, res.text
    assert res.json().get("displayName") == "engineering-renamed"

    res = client.delete(f"/api/v1/scim/v2/Groups/{group_id}", headers=_auth(token))
    assert res.status_code == 204, res.text
    assert called["audit"] >= 1

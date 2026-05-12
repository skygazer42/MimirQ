from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.core.database import get_db
from app.models.dataset import DatasetPermissionEnum


class _DummyDB:
    def commit(self) -> None:
        return None

    def refresh(self, _obj) -> None:  # noqa: ANN001
        return None


def _override_get_db():  # noqa: ANN202
    yield _DummyDB()


def test_dataset_create_and_update_round_trips_group_allowlist(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.api.v1.datasets as ds_api
    from app.api.schemas.dataset import DatasetOut

    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    group_id_1 = uuid.uuid4()
    group_id_2 = uuid.uuid4()

    now = datetime.now(UTC)
    dataset_obj = SimpleNamespace(
        id=dataset_id,
        tenant_id=tenant_id,
        name="DS",
        description=None,
        permission=DatasetPermissionEnum.PARTIAL_MEMBERS,
        owner_id="owner",
        dataset_metadata={},
        created_at=now,
        updated_at=now,
    )

    store = {
        "members": [],
        "groups": [],
    }

    monkeypatch.setattr(ds_api, "audit_log_event", lambda *_a, **_k: None, raising=False)

    def _create_dataset(*, db, tenant_id, name, description, permission, owner_id, partial_members, partial_groups):  # noqa: ANN001
        assert tenant_id == dataset_obj.tenant_id
        assert owner_id == "owner"
        assert permission == DatasetPermissionEnum.PARTIAL_MEMBERS
        store["members"] = list(partial_members or [])
        store["groups"] = list(partial_groups or [])
        return dataset_obj

    def _get_dataset(_db, _tenant_id, _dataset_id):  # noqa: ANN001
        assert _tenant_id == tenant_id
        assert _dataset_id == dataset_id
        return dataset_obj

    def _update_dataset(*, db, dataset, updater_id, name, description, permission, partial_members, partial_groups):  # noqa: ANN001
        assert dataset is dataset_obj
        assert updater_id == "owner"
        # Keep permission unchanged for this test.
        if name is not None:
            dataset_obj.name = name
        if description is not None:
            dataset_obj.description = description
        store["members"] = list(partial_members or [])
        store["groups"] = list(partial_groups or [])
        return dataset_obj

    monkeypatch.setattr(ds_api.DatasetService, "create_dataset", _create_dataset, raising=True)
    monkeypatch.setattr(ds_api.DatasetService, "get_dataset", _get_dataset, raising=True)
    monkeypatch.setattr(ds_api.DatasetService, "assert_dataset_writable", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(ds_api.DatasetService, "update_dataset", _update_dataset, raising=True)
    monkeypatch.setattr(ds_api.DatasetPermissionService, "get_dataset_partial_member_list", lambda *_a, **_k: list(store["members"]), raising=True)
    monkeypatch.setattr(ds_api.DatasetGroupPermissionService, "get_dataset_partial_group_list", lambda *_a, **_k: list(store["groups"]), raising=True)

    def _override_get_tenant_id() -> uuid.UUID:
        return tenant_id

    def _override_get_current_account_id() -> str:
        return "owner"

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = _override_get_tenant_id
    app.dependency_overrides[get_current_account_id] = _override_get_current_account_id
    app.post("/api/v1/datasets", status_code=201, response_model=DatasetOut)(ds_api.create_dataset)
    app.patch("/api/v1/datasets/{dataset_id}", response_model=DatasetOut)(ds_api.update_dataset)
    client = TestClient(app)

    res = client.post(
        "/api/v1/datasets",
        json={
            "name": "DS",
            "permission": "partial_members",
            "partial_member_list": ["alice"],
            "partial_group_list": [str(group_id_1)],
        },
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body.get("permission") == "partial_members"
    assert body.get("partial_member_list") == ["alice"]
    assert body.get("partial_group_list") == [str(group_id_1)]

    res = client.patch(
        f"/api/v1/datasets/{dataset_id}",
        json={
            "permission": "partial_members",
            "partial_member_list": ["bob"],
            "partial_group_list": [str(group_id_2)],
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body.get("partial_member_list") == ["bob"]
    assert body.get("partial_group_list") == [str(group_id_2)]


def test_document_access_api_enforces_group_allowlist(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.api.v1.document_access as docs_api
    import app.services.document_access_service as access_service
    from app.api.schemas.document import DocumentAccessInfo

    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    document_id = uuid.uuid4()
    group_id = uuid.uuid4()

    dataset_obj = SimpleNamespace(id=dataset_id, tenant_id=tenant_id, owner_id="owner")
    doc = SimpleNamespace(id=document_id, tenant_id=tenant_id, dataset_id=dataset_id, owner_id="doc-owner", access_mode="partial_members")

    current_account = {"value": "bob"}

    class _FakeQuery:
        def __init__(self, *, model, db):  # noqa: ANN001
            self._model = model
            self._db = db
            self._filters: dict[str, object] = {}

        def filter(self, *conds, **_kwargs):  # noqa: ANN001
            # Extract basic equality filters (key == value).
            for expr in conds:
                left_key = getattr(getattr(expr, "left", None), "key", None)
                right_val = getattr(getattr(expr, "right", None), "value", None)
                if left_key:
                    self._filters[str(left_key)] = right_val
            return self

        def first(self):  # noqa: ANN201
            if self._model is docs_api.DBDocument:
                if self._filters.get("id") == doc.id and self._filters.get("tenant_id") == doc.tenant_id:
                    return doc
                return None

            if self._model is access_service.DocumentPermission:
                tid = self._filters.get("tenant_id")
                did = self._filters.get("document_id")
                aid = self._filters.get("account_id")
                if (tid, did, aid) in self._db.member_perms:
                    return object()
                return None

            return None

    class _FakeDB:
        def __init__(self) -> None:
            self.member_allowlist: dict[uuid.UUID, list[str]] = {document_id: []}
            self.group_allowlist: dict[uuid.UUID, list[uuid.UUID]] = {document_id: [group_id]}
            self.member_perms: set[tuple[uuid.UUID, uuid.UUID, str]] = set()

        def query(self, model):  # noqa: ANN001
            return _FakeQuery(model=model, db=self)

        def commit(self) -> None:
            return None

        def refresh(self, _obj) -> None:  # noqa: ANN001
            return None

    db = _FakeDB()

    # Minimal no-op dataset permission hooks.
    monkeypatch.setattr(docs_api.DatasetService, "ensure_member", lambda *_a, **_k: SimpleNamespace(role="owner"), raising=True)
    monkeypatch.setattr(docs_api.DatasetService, "get_dataset", lambda *_a, **_k: dataset_obj, raising=True)
    monkeypatch.setattr(docs_api.DatasetService, "assert_dataset_readable", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(docs_api.DatasetService, "assert_dataset_writable", lambda *_a, **_k: None, raising=True)

    # Persist allowlists in-memory via service monkeypatching.
    def _upd_members(_db, _tenant_id, _document_id, member_ids, **_kw):  # noqa: ANN001
        db.member_allowlist[_document_id] = list(member_ids or [])
        db.member_perms = {(tenant_id, _document_id, mid) for mid in db.member_allowlist[_document_id]}

    def _clr_members(_db, _tenant_id, _document_id):  # noqa: ANN001
        db.member_allowlist[_document_id] = []
        db.member_perms = {(t, d, a) for (t, d, a) in db.member_perms if d != _document_id}

    def _get_members(_db, _tenant_id, _document_id):  # noqa: ANN001
        return list(db.member_allowlist.get(_document_id, []))

    def _upd_groups(_db, _tenant_id, _document_id, group_ids, **_kw):  # noqa: ANN001
        db.group_allowlist[_document_id] = list(group_ids or [])

    def _clr_groups(_db, _tenant_id, _document_id):  # noqa: ANN001
        db.group_allowlist[_document_id] = []

    def _get_groups(_db, _tenant_id, _document_id):  # noqa: ANN001
        return list(db.group_allowlist.get(_document_id, []))

    monkeypatch.setattr(docs_api.DocumentPermissionService, "update_partial_member_list", _upd_members, raising=True)
    monkeypatch.setattr(docs_api.DocumentPermissionService, "clear_partial_member_list", _clr_members, raising=True)
    monkeypatch.setattr(docs_api.DocumentPermissionService, "get_document_partial_member_list", _get_members, raising=True)

    monkeypatch.setattr(docs_api.DocumentGroupPermissionService, "update_partial_group_list", _upd_groups, raising=True)
    monkeypatch.setattr(docs_api.DocumentGroupPermissionService, "clear_partial_group_list", _clr_groups, raising=True)
    monkeypatch.setattr(docs_api.DocumentGroupPermissionService, "get_document_partial_group_list", _get_groups, raising=True)

    monkeypatch.setattr(docs_api, "audit_log_event", lambda *_a, **_k: None, raising=False)

    # Group membership mapping for access check.
    membership = {"bob": [group_id], "charlie": []}
    monkeypatch.setattr(
        access_service.TenantGroupService,
        "resolve_account_group_ids",
        lambda *_a, **_k: membership.get(current_account["value"], []),
        raising=True,
    )

    def _override_get_db():  # noqa: ANN202
        yield db

    def _override_get_tenant_id() -> uuid.UUID:
        return tenant_id

    def _override_get_current_account_id() -> str:
        return current_account["value"]

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = _override_get_tenant_id
    app.dependency_overrides[get_current_account_id] = _override_get_current_account_id
    app.get("/api/v1/documents/{document_id}/access", response_model=DocumentAccessInfo)(docs_api.get_document_access)
    client = TestClient(app)

    current_account["value"] = "bob"
    res = client.get(f"/api/v1/documents/{document_id}/access")
    assert res.status_code == 200, res.text

    current_account["value"] = "charlie"
    res = client.get(f"/api/v1/documents/{document_id}/access")
    assert res.status_code == 403, res.text


def test_document_access_put_get_round_trips_member_and_group_lists(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.api.v1.document_access as docs_api
    from app.api.schemas.document import DocumentAccessInfo

    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    document_id = uuid.uuid4()
    group_id = uuid.uuid4()

    dataset_obj = SimpleNamespace(id=dataset_id, tenant_id=tenant_id, owner_id="owner")
    doc = SimpleNamespace(id=document_id, tenant_id=tenant_id, dataset_id=dataset_id, owner_id=None, access_mode=None)

    class _FakeQuery:
        def __init__(self, *, model):  # noqa: ANN001
            self._model = model
            self._filters: dict[str, object] = {}

        def filter(self, *conds, **_kwargs):  # noqa: ANN001
            for expr in conds:
                left_key = getattr(getattr(expr, "left", None), "key", None)
                right_val = getattr(getattr(expr, "right", None), "value", None)
                if left_key:
                    self._filters[str(left_key)] = right_val
            return self

        def first(self):  # noqa: ANN201
            if self._model is docs_api.DBDocument:
                if self._filters.get("id") == doc.id and self._filters.get("tenant_id") == doc.tenant_id:
                    return doc
                return None
            # `_assert_document_acl_readable` might query DocumentPermission for read checks.
            if self._model is docs_api.DocumentPermission:
                return object()  # owner bypass covers the rest; keep simple
            return None

    class _FakeDB:
        def __init__(self) -> None:
            self.member_allowlist: dict[uuid.UUID, list[str]] = {}
            self.group_allowlist: dict[uuid.UUID, list[uuid.UUID]] = {}

        def query(self, model):  # noqa: ANN001
            return _FakeQuery(model=model)

        def commit(self) -> None:
            return None

        def refresh(self, _obj) -> None:  # noqa: ANN001
            return None

    db = _FakeDB()

    monkeypatch.setattr(docs_api.DatasetService, "ensure_member", lambda *_a, **_k: SimpleNamespace(role="owner"), raising=True)
    monkeypatch.setattr(docs_api.DatasetService, "get_dataset", lambda *_a, **_k: dataset_obj, raising=True)
    monkeypatch.setattr(docs_api.DatasetService, "assert_dataset_readable", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(docs_api.DatasetService, "assert_dataset_writable", lambda *_a, **_k: None, raising=True)

    monkeypatch.setattr(docs_api, "audit_log_event", lambda *_a, **_k: None, raising=False)

    def _upd_members(_db, _tenant_id, _document_id, member_ids, **_kw):  # noqa: ANN001
        db.member_allowlist[_document_id] = list(member_ids or [])

    def _clr_members(_db, _tenant_id, _document_id):  # noqa: ANN001
        db.member_allowlist[_document_id] = []

    def _get_members(_db, _tenant_id, _document_id):  # noqa: ANN001
        return list(db.member_allowlist.get(_document_id, []))

    def _upd_groups(_db, _tenant_id, _document_id, group_ids, **_kw):  # noqa: ANN001
        db.group_allowlist[_document_id] = list(group_ids or [])

    def _clr_groups(_db, _tenant_id, _document_id):  # noqa: ANN001
        db.group_allowlist[_document_id] = []

    def _get_groups(_db, _tenant_id, _document_id):  # noqa: ANN001
        return list(db.group_allowlist.get(_document_id, []))

    monkeypatch.setattr(docs_api.DocumentPermissionService, "update_partial_member_list", _upd_members, raising=True)
    monkeypatch.setattr(docs_api.DocumentPermissionService, "clear_partial_member_list", _clr_members, raising=True)
    monkeypatch.setattr(docs_api.DocumentPermissionService, "get_document_partial_member_list", _get_members, raising=True)

    monkeypatch.setattr(docs_api.DocumentGroupPermissionService, "update_partial_group_list", _upd_groups, raising=True)
    monkeypatch.setattr(docs_api.DocumentGroupPermissionService, "clear_partial_group_list", _clr_groups, raising=True)
    monkeypatch.setattr(docs_api.DocumentGroupPermissionService, "get_document_partial_group_list", _get_groups, raising=True)

    def _override_get_db():  # noqa: ANN202
        yield db

    def _override_get_tenant_id() -> uuid.UUID:
        return tenant_id

    def _override_get_current_account_id() -> str:
        return "owner"

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = _override_get_tenant_id
    app.dependency_overrides[get_current_account_id] = _override_get_current_account_id
    app.put("/api/v1/documents/{document_id}/access", response_model=DocumentAccessInfo)(docs_api.put_document_access)
    app.get("/api/v1/documents/{document_id}/access", response_model=DocumentAccessInfo)(docs_api.get_document_access)
    client = TestClient(app)

    res = client.put(
        f"/api/v1/documents/{document_id}/access",
        json={
            "mode": "partial_members",
            "partial_member_list": ["alice"],
            "partial_group_list": [str(group_id)],
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body.get("mode") == "partial_members"
    assert body.get("partial_member_list") == ["alice"]
    assert body.get("partial_group_list") == [str(group_id)]

    res = client.get(f"/api/v1/documents/{document_id}/access")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body.get("partial_member_list") == ["alice"]
    assert body.get("partial_group_list") == [str(group_id)]

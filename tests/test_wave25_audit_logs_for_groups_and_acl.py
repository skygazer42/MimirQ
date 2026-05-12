from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.api.schemas.document import DocumentAccessUpdateRequest
from app.api.schemas.group import TenantGroupCreateRequest, TenantGroupMembersUpdateRequest


def test_groups_member_changes_emit_audit_logs_without_pii(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.api.v1.groups as groups

    tenant_id = uuid4()
    group_id = uuid4()
    account_id = "actor"

    monkeypatch.setattr(groups, "ensure_tenant_permission", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(groups.TenantGroupService, "add_members", lambda *_a, **_k: 2, raising=True)

    events: list[dict] = []

    def _audit(_db, **kwargs):  # noqa: ANN001
        events.append(kwargs)

    monkeypatch.setattr(groups, "audit_log_event", _audit, raising=False)

    class _DB:  # noqa: WPS431
        def commit(self) -> None:
            return None

    payload = TenantGroupMembersUpdateRequest(member_ids=["alice", "bob", "alice"])
    res = groups.add_group_members(group_id=group_id, payload=payload, tenant_id=tenant_id, account_id=account_id, db=_DB())

    assert res.updated == 2
    assert events, "expected audit_log_event to be called"
    evt = events[-1]
    assert evt.get("action") == "group.members.add"
    details = evt.get("details") or {}
    assert isinstance(details.get("member_count_requested"), int)
    assert isinstance(details.get("member_count_updated"), int)
    assert "member_ids" not in details
    assert "alice" not in str(details)
    assert "bob" not in str(details)


def test_groups_create_emits_audit_log(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.api.v1.groups as groups

    tenant_id = uuid4()
    group_id = uuid4()
    account_id = "actor"

    monkeypatch.setattr(groups, "ensure_tenant_permission", lambda *_a, **_k: None, raising=True)

    group_obj = SimpleNamespace(
        id=group_id,
        tenant_id=tenant_id,
        name="Engineering",
        external_id="ext-1",
        created_at=datetime.now(UTC),
        updated_at=None,
    )
    monkeypatch.setattr(groups.TenantGroupService, "create_group", lambda *_a, **_k: group_obj, raising=True)

    events: list[dict] = []

    def _audit(_db, **kwargs):  # noqa: ANN001
        events.append(kwargs)

    monkeypatch.setattr(groups, "audit_log_event", _audit, raising=False)

    class _DB:  # noqa: WPS431
        def commit(self) -> None:
            return None

    payload = TenantGroupCreateRequest(name="Engineering", external_id="ext-1")
    out = groups.create_group(payload=payload, tenant_id=tenant_id, account_id=account_id, db=_DB())
    assert str(out.id) == str(group_id)

    assert events, "expected audit_log_event to be called"
    evt = events[-1]
    assert evt.get("action") == "group.create"
    details = evt.get("details") or {}
    # Do not leak external_id (IdP identifier) directly.
    assert "external_id" not in details


@pytest.mark.asyncio
async def test_document_access_update_emits_audit_log_without_pii(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.api.v1.document_access as docs

    tenant_id = uuid4()
    dataset_id = uuid4()
    document_id = uuid4()
    account_id = "actor"
    group_id = uuid4()

    # Avoid touching real dataset/doc services.
    monkeypatch.setattr(docs.DatasetService, "ensure_member", lambda *_a, **_k: SimpleNamespace(role="owner"), raising=True)
    monkeypatch.setattr(docs.DatasetService, "get_dataset", lambda *_a, **_k: SimpleNamespace(), raising=True)
    monkeypatch.setattr(docs.DatasetService, "assert_dataset_writable", lambda *_a, **_k: None, raising=True)

    monkeypatch.setattr(docs.DocumentPermissionService, "update_partial_member_list", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(docs.DocumentGroupPermissionService, "update_partial_group_list", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(docs.DocumentPermissionService, "clear_partial_member_list", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(docs.DocumentGroupPermissionService, "clear_partial_group_list", lambda *_a, **_k: None, raising=True)

    monkeypatch.setattr(docs.DocumentPermissionService, "get_document_partial_member_list", lambda *_a, **_k: ["u1", "u2"], raising=True)
    monkeypatch.setattr(docs.DocumentGroupPermissionService, "get_document_partial_group_list", lambda *_a, **_k: [group_id], raising=True)

    events: list[dict] = []

    def _audit(_db, **kwargs):  # noqa: ANN001
        events.append(kwargs)

    monkeypatch.setattr(docs, "audit_log_event", _audit, raising=False)

    doc = SimpleNamespace(id=document_id, tenant_id=tenant_id, dataset_id=dataset_id, owner_id=None, access_mode=None)

    class _FakeQuery:  # noqa: WPS431
        def __init__(self, obj):  # noqa: ANN001
            self._obj = obj

        def filter(self, *_a, **_k):  # noqa: ANN001
            return self

        def first(self):  # noqa: ANN201
            return self._obj

    class _DB:  # noqa: WPS431
        def query(self, *_a, **_k):  # noqa: ANN001
            return _FakeQuery(doc)

        def commit(self) -> None:
            return None

        def refresh(self, _obj) -> None:  # noqa: ANN001
            return None

    payload = DocumentAccessUpdateRequest(
        mode="partial_members",
        partial_member_list=["alice", "bob"],
        partial_group_list=[group_id],
    )
    out = await docs.put_document_access(
        document_id=document_id,
        payload=payload,
        tenant_id=tenant_id,
        account_id=account_id,
        db=_DB(),
    )
    assert out.mode == "partial_members"
    assert events, "expected audit_log_event to be called"
    evt = events[-1]
    assert evt.get("action") == "document.access.update"
    details = evt.get("details") or {}
    assert isinstance(details.get("partial_member_count"), int)
    assert isinstance(details.get("partial_group_count"), int)
    assert "partial_member_list" not in details
    assert "partial_group_list" not in details
    assert "alice" not in str(details)
    assert "bob" not in str(details)


def test_dataset_group_allowlist_update_emits_audit_log_without_pii(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.services.dataset_service as ds

    tenant_id = uuid4()
    dataset_id = uuid4()
    group_id = uuid4()

    events: list[dict] = []

    def _audit(_db, **kwargs):  # noqa: ANN001
        events.append(kwargs)

    monkeypatch.setattr(ds, "audit_log_event", _audit, raising=False)

    class _FakeQuery:  # noqa: WPS431
        def __init__(self, *, rows=None, delete_count=0):  # noqa: ANN001
            self._rows = list(rows or [])
            self._delete_count = int(delete_count or 0)

        def filter(self, *_a, **_k):  # noqa: ANN001
            return self

        def all(self):  # noqa: ANN201
            return list(self._rows)

        def delete(self, *args, **kwargs):  # noqa: ANN001, ANN201
            return self._delete_count

    class _DB:  # noqa: WPS431
        def __init__(self) -> None:
            self.added = []

        def query(self, *args, **_kwargs):  # noqa: ANN001
            if len(args) == 1:
                arg = args[0]
                # TenantGroup.id lookup for existence validation.
                if getattr(arg, "key", None) == "id" and getattr(getattr(arg, "class_", None), "__name__", None) == "TenantGroup":
                    return _FakeQuery(rows=[(group_id,)])
                # DatasetGroupPermission delete query.
                if getattr(arg, "__name__", None) == "DatasetGroupPermission":
                    return _FakeQuery(rows=[], delete_count=1)
            return _FakeQuery(rows=[], delete_count=0)

        def add_all(self, items) -> None:  # noqa: ANN001
            self.added.extend(list(items or []))

        def commit(self) -> None:
            return None

    ds.DatasetGroupPermissionService.update_partial_group_list(
        _DB(),
        tenant_id,
        dataset_id,
        [group_id, group_id],
    )

    assert events, "expected audit_log_event to be called"
    evt = events[-1]
    assert evt.get("action") == "dataset.access.groups.update"
    details = evt.get("details") or {}
    assert isinstance(details.get("group_count"), int)
    assert "group_ids" not in details

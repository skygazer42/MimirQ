from __future__ import annotations

from uuid import uuid4

import pytest

from app.models.dataset import DatasetPermissionEnum


class _FakeQuery:
    def __init__(self, *, first=None, rows=None):  # noqa: ANN001
        self._first = first
        self._rows = list(rows or [])

    def filter(self, *_args, **_kwargs):  # noqa: ANN001
        return self

    def first(self):  # noqa: ANN201
        return self._first

    def all(self):  # noqa: ANN201
        return list(self._rows)


class _FakeSession:
    def __init__(  # noqa: ANN001
        self,
        *,
        member_perm_exists: bool,
        group_ids: list,
        group_perm_exists: bool,
    ):
        self._member_perm_exists = bool(member_perm_exists)
        self._group_ids = list(group_ids or [])
        self._group_perm_exists = bool(group_perm_exists)

    def query(self, *args, **_kwargs):  # noqa: ANN001
        # DatasetPermission existence check.
        if len(args) == 1 and getattr(args[0], "__name__", None) == "DatasetPermission":
            return _FakeQuery(first=("row",) if self._member_perm_exists else None)

        if len(args) == 1:
            col = args[0]

            # TenantGroupMember.group_id -> account group ids.
            if getattr(col, "key", None) == "group_id" and getattr(getattr(col, "class_", None), "__name__", None) == "TenantGroupMember":
                return _FakeQuery(rows=[(gid,) for gid in self._group_ids])

            # DatasetGroupPermission.id existence check.
            if getattr(col, "key", None) == "id" and getattr(getattr(col, "class_", None), "__name__", None) == "DatasetGroupPermission":
                return _FakeQuery(first=("row",) if self._group_perm_exists else None)

        return _FakeQuery(first=None, rows=[])


class _Dataset:
    def __init__(self, *, tenant_id, dataset_id, owner_id, permission):  # noqa: ANN001
        self.tenant_id = tenant_id
        self.id = dataset_id
        self.owner_id = owner_id
        self.permission = permission


def test_check_dataset_permission_allows_via_group_membership() -> None:
    import app.services.dataset_service as ds

    tenant_id = uuid4()
    dataset_id = uuid4()
    group_id = uuid4()

    dataset = _Dataset(
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        owner_id="alice",
        permission=DatasetPermissionEnum.PARTIAL_MEMBERS,
    )
    db = _FakeSession(
        member_perm_exists=False,
        group_ids=[group_id],
        group_perm_exists=True,
    )
    assert ds.DatasetService.check_dataset_permission(db, dataset, "bob") is True


def test_assert_dataset_writable_allows_via_group_membership(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.services.dataset_service as ds

    tenant_id = uuid4()
    dataset_id = uuid4()
    group_id = uuid4()

    dataset = _Dataset(
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        owner_id="alice",
        permission=DatasetPermissionEnum.PARTIAL_MEMBERS,
    )
    db = _FakeSession(
        member_perm_exists=False,
        group_ids=[group_id],
        group_perm_exists=True,
    )

    class _Member:
        role = "editor"

    monkeypatch.setattr(ds.DatasetService, "ensure_member", lambda *_a, **_k: _Member(), raising=True)

    # Should not raise.
    ds.DatasetService.assert_dataset_writable(db, dataset, "bob")


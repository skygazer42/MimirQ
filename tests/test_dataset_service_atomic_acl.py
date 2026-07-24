import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException


class _Query:
    def __init__(self, first_result):  # noqa: ANN001
        self._first_result = first_result

    def filter(self, *_args, **_kwargs):  # noqa: ANN001
        return self

    def first(self):  # noqa: ANN201
        return self._first_result


class _AtomicSession:
    def __init__(self, *, first_results=None, tracked_dataset=None) -> None:  # noqa: ANN001
        self._first_results = list(first_results or [])
        self._tracked_dataset = tracked_dataset
        self.added: list[object] = []
        self.persisted_added: list[object] = []
        self.flush_calls = 0
        self.commit_calls = 0
        self.rollback_calls = 0
        self.refresh_calls = 0
        self._persisted_dataset = self._snapshot_dataset()

    def _snapshot_dataset(self) -> dict[str, object] | None:
        if self._tracked_dataset is None:
            return None
        return {
            "name": getattr(self._tracked_dataset, "name", None),
            "description": getattr(self._tracked_dataset, "description", None),
            "permission": getattr(self._tracked_dataset, "permission", None),
            "dataset_metadata": dict(getattr(self._tracked_dataset, "dataset_metadata", None) or {}),
        }

    def query(self, _model):  # noqa: ANN001, ANN201
        first_result = self._first_results.pop(0) if self._first_results else None
        return _Query(first_result)

    def add(self, obj) -> None:  # noqa: ANN001
        self.added.append(obj)

    def add_all(self, rows) -> None:  # noqa: ANN001
        self.added.extend(rows)

    def flush(self) -> None:
        self.flush_calls += 1
        for obj in self.added:
            if getattr(obj, "id", None) is None:
                obj.id = uuid.uuid4()

    def commit(self) -> None:
        self.commit_calls += 1
        self.persisted_added = list(self.added)
        self._persisted_dataset = self._snapshot_dataset()

    def refresh(self, _obj) -> None:  # noqa: ANN001
        self.refresh_calls += 1

    def rollback(self) -> None:
        self.rollback_calls += 1
        if self._tracked_dataset is not None and self._persisted_dataset is not None:
            self._tracked_dataset.name = self._persisted_dataset["name"]
            self._tracked_dataset.description = self._persisted_dataset["description"]
            self._tracked_dataset.permission = self._persisted_dataset["permission"]
            self._tracked_dataset.dataset_metadata = dict(self._persisted_dataset["dataset_metadata"] or {})
        self.added.clear()


def test_create_dataset_rolls_back_when_partial_member_acl_update_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.models.dataset import DatasetPermissionEnum
    from app.services.dataset_service import DatasetGroupPermissionService, DatasetPermissionService, DatasetService

    tenant_id = uuid.uuid4()
    db = _AtomicSession(first_results=[None])
    group_update_calls: list[bool] = []

    monkeypatch.setattr(
        DatasetService,
        "ensure_member",
        lambda *_args, **_kwargs: SimpleNamespace(role="owner"),
        raising=True,
    )

    def _fail_partial_member_update(*_args, **_kwargs):  # noqa: ANN001
        raise HTTPException(status_code=400, detail="Member(s) not in tenant: ghost-user")

    monkeypatch.setattr(
        DatasetPermissionService,
        "update_partial_member_list",
        _fail_partial_member_update,
        raising=True,
    )
    monkeypatch.setattr(
        DatasetGroupPermissionService,
        "update_partial_group_list",
        lambda *_args, **_kwargs: group_update_calls.append(True),
        raising=True,
    )

    with pytest.raises(HTTPException, match="Member\\(s\\) not in tenant: ghost-user") as exc_info:
        DatasetService.create_dataset(
            db=db,
            tenant_id=tenant_id,
            name="atomic-create",
            description="should roll back",
            permission=DatasetPermissionEnum.PARTIAL_MEMBERS,
            owner_id="owner-1",
            partial_members=["ghost-user"],
            partial_groups=[uuid.uuid4()],
        )

    assert exc_info.value.status_code == 400
    assert db.flush_calls == 1
    assert db.commit_calls == 0
    assert db.rollback_calls == 1
    assert db.persisted_added == []
    assert db.added == []
    assert group_update_calls == []


def test_update_dataset_rolls_back_dataset_fields_when_group_acl_update_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.models.dataset import DatasetPermissionEnum
    from app.services.dataset_service import DatasetGroupPermissionService, DatasetPermissionService, DatasetService

    tenant_id = uuid.uuid4()
    dataset = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        name="before",
        description="before description",
        permission=DatasetPermissionEnum.ALL_TEAM_MEMBERS,
        dataset_metadata={},
    )
    db = _AtomicSession(first_results=[None], tracked_dataset=dataset)
    member_update_calls: list[bool] = []

    monkeypatch.setattr(
        DatasetService,
        "ensure_member",
        lambda *_args, **_kwargs: SimpleNamespace(role="owner"),
        raising=True,
    )
    monkeypatch.setattr(
        DatasetPermissionService,
        "update_partial_member_list",
        lambda *_args, **_kwargs: member_update_calls.append(True),
        raising=True,
    )

    def _fail_group_update(*_args, **_kwargs):  # noqa: ANN001
        raise HTTPException(status_code=400, detail="Unknown tenant groups: missing-group")

    monkeypatch.setattr(
        DatasetGroupPermissionService,
        "update_partial_group_list",
        _fail_group_update,
        raising=True,
    )

    with pytest.raises(HTTPException, match="Unknown tenant groups: missing-group") as exc_info:
        DatasetService.update_dataset(
            db=db,
            dataset=dataset,
            updater_id="owner-1",
            name="after",
            description="after description",
            permission=DatasetPermissionEnum.PARTIAL_MEMBERS,
            partial_members=["member-2"],
            partial_groups=[uuid.uuid4()],
            dataset_metadata={"embedding_defaults": {"model": "embed-a"}},
        )

    assert exc_info.value.status_code == 400
    assert member_update_calls == [True]
    assert db.commit_calls == 0
    assert db.rollback_calls == 1
    assert dataset.name == "before"
    assert dataset.description == "before description"
    assert dataset.permission == DatasetPermissionEnum.ALL_TEAM_MEMBERS
    assert dataset.dataset_metadata == {}

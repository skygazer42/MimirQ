from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy.sql.elements import BinaryExpression, BooleanClauseList

import app.api.v1.connectors  # noqa: F401
from app.api.v1 import connectors_runs as connectors_runs_module
from app.api.v1 import ingestion_runs as ingestion_runs_module


@dataclass
class _FakeRun:
    id: UUID
    tenant_id: UUID
    dataset_id: UUID | None
    created_at: datetime
    documents: list[object] = field(default_factory=list)
    kind: str = "upload"
    requested_by: str | None = "member-1"
    status: str = "succeeded"
    config: dict[str, object] = field(default_factory=dict)
    stats: dict[str, object] = field(default_factory=dict)
    error_message: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    connector_id: str = "url_batch"


class _FakeQuery:
    def __init__(self, *, runs: list[_FakeRun]) -> None:
        self._runs = list(runs)
        self._skip = 0
        self._limit: int | None = None

    def filter(self, *conditions):  # noqa: ANN002, ANN202
        for condition in conditions:
            self._runs = [run for run in self._runs if self._matches(run, condition)]
        return self

    @classmethod
    def _matches(cls, run: _FakeRun, condition) -> bool:  # noqa: ANN001
        if isinstance(condition, BooleanClauseList):
            clauses = [cls._matches(run, clause) for clause in condition.clauses]
            operator_name = getattr(condition.operator, "__name__", "")
            if operator_name == "and_":
                return all(clauses)
            if operator_name == "or_":
                return any(clauses)
            raise AssertionError(f"unsupported boolean operator: {operator_name}")
        if not isinstance(condition, BinaryExpression):
            raise AssertionError(f"unsupported filter expression: {type(condition).__name__}")

        key = getattr(condition.left, "key", None)
        value = getattr(condition.right, "value", None)
        operator_name = getattr(condition.operator, "__name__", "")
        if not key:
            raise AssertionError("filter expression has no model field")
        actual = getattr(run, key)
        if operator_name == "eq":
            return actual == value
        if operator_name == "ne":
            return actual != value
        if operator_name == "in_op":
            return actual in set(value or [])
        if operator_name == "not_in_op":
            return actual not in set(value or [])
        raise AssertionError(f"unsupported binary operator: {operator_name}")

    def count(self) -> int:
        return len(self._filtered_runs())

    def options(self, *_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
        return self

    def order_by(self, *_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
        return self

    def offset(self, skip: int):  # noqa: ANN201
        self._skip = skip
        return self

    def limit(self, limit: int):  # noqa: ANN201
        self._limit = limit
        return self

    def all(self) -> list[_FakeRun]:
        runs = sorted(self._filtered_runs(), key=lambda run: run.created_at, reverse=True)
        if self._skip:
            runs = runs[self._skip :]
        if self._limit is not None:
            runs = runs[: self._limit]
        return runs

    def _filtered_runs(self) -> list[_FakeRun]:
        return list(self._runs)


class _FakeSession:
    def __init__(self, *, query: _FakeQuery) -> None:
        self._query = query

    def query(self, _model):  # noqa: ANN001, ANN201
        return self._query


class _DatasetRef:
    def __init__(self, dataset_id: UUID) -> None:
        self.id = dataset_id


class _TenantMember:
    def __init__(self, role: str = "editor") -> None:
        self.role = role


def _build_runs() -> tuple[UUID, list[_FakeRun], set[UUID]]:
    tenant_id = uuid4()
    blocked_dataset_ids = [uuid4(), uuid4()]
    allowed_dataset_ids = [uuid4(), uuid4()]
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    runs = [
        _FakeRun(id=uuid4(), tenant_id=tenant_id, dataset_id=blocked_dataset_ids[0], created_at=base + timedelta(minutes=4)),
        _FakeRun(id=uuid4(), tenant_id=tenant_id, dataset_id=blocked_dataset_ids[1], created_at=base + timedelta(minutes=3)),
        _FakeRun(id=uuid4(), tenant_id=tenant_id, dataset_id=allowed_dataset_ids[0], created_at=base + timedelta(minutes=2)),
        _FakeRun(id=uuid4(), tenant_id=tenant_id, dataset_id=allowed_dataset_ids[1], created_at=base + timedelta(minutes=1)),
    ]
    return tenant_id, runs, set(allowed_dataset_ids)


def _install_acl_guards(monkeypatch: pytest.MonkeyPatch, *, dataset_service, allowed_dataset_ids: set[UUID]) -> dict[str, int]:
    calls = {"get_dataset": 0, "assert_dataset_writable": 0}

    monkeypatch.setattr(dataset_service, "ensure_member", lambda *_args, **_kwargs: _TenantMember(), raising=True)

    def _get_dataset(_db, tenant_id: UUID, dataset_id: UUID) -> _DatasetRef:  # noqa: ANN001
        assert tenant_id
        calls["get_dataset"] += 1
        return _DatasetRef(dataset_id)

    def _assert_dataset_writable(_db, dataset: _DatasetRef, _account_id: str) -> None:  # noqa: ANN001
        calls["assert_dataset_writable"] += 1
        if dataset.id not in allowed_dataset_ids:
            raise HTTPException(status_code=403, detail="No dataset write permission")

    monkeypatch.setattr(dataset_service, "get_dataset", _get_dataset, raising=True)
    monkeypatch.setattr(dataset_service, "assert_dataset_writable", _assert_dataset_writable, raising=True)
    return calls


def test_list_ingestion_runs_applies_acl_before_count_and_pagination(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id, runs, allowed_dataset_ids = _build_runs()
    db = _FakeSession(query=_FakeQuery(runs=runs))
    calls = _install_acl_guards(monkeypatch, dataset_service=ingestion_runs_module.DatasetService, allowed_dataset_ids=allowed_dataset_ids)
    monkeypatch.setattr(
        ingestion_runs_module,
        "_writable_dataset_ids_subquery",
        lambda **_kwargs: list(allowed_dataset_ids),
        raising=True,
    )

    response = ingestion_runs_module.list_ingestion_runs(
        skip=0,
        limit=2,
        dataset_id=None,
        status=None,
        kind=None,
        tenant_id=tenant_id,
        account_id="member-1",
        db=db,
    )

    assert response.total == 2
    assert [item.id for item in response.items] == [runs[2].id, runs[3].id]
    assert calls == {"get_dataset": 0, "assert_dataset_writable": 0}


def test_list_connector_runs_applies_acl_before_count_and_pagination(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id, runs, allowed_dataset_ids = _build_runs()
    db = _FakeSession(query=_FakeQuery(runs=runs))
    calls = _install_acl_guards(
        monkeypatch,
        dataset_service=connectors_runs_module.connectors_module.DatasetService,
        allowed_dataset_ids=allowed_dataset_ids,
    )
    monkeypatch.setattr(
        connectors_runs_module,
        "_writable_dataset_ids_subquery",
        lambda **_kwargs: list(allowed_dataset_ids),
        raising=True,
    )
    monkeypatch.setattr(
        connectors_runs_module.connectors_module,
        "_fetch_connector_run_acl_summaries",
        lambda *_args, **_kwargs: {},
        raising=True,
    )
    monkeypatch.setattr(
        connectors_runs_module.connectors_module,
        "_run_out",
        lambda run, acl_summary=None: {"id": run.id, "dataset_id": run.dataset_id, "acl_summary": acl_summary},
        raising=True,
    )

    response = connectors_runs_module.list_connector_runs(
        params=connectors_runs_module.ConnectorRunListParams(skip=0, limit=2, dataset_id=None),
        tenant_id=tenant_id,
        account_id="member-1",
        db=db,
    )

    assert response["total"] == 2
    assert [item["id"] for item in response["items"]] == [runs[2].id, runs[3].id]
    assert calls == {"get_dataset": 0, "assert_dataset_writable": 0}

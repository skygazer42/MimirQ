from __future__ import annotations

import operator
import uuid
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.core.database import get_db
from app.models.dataset import Dataset, DatasetPermission, DatasetPermissionEnum
from app.models.document import Document, DocumentPermission
from app.models.group_permissions import DatasetGroupPermission, DocumentGroupPermission
from app.models.tenant_group import TenantGroup, TenantGroupMember
from app.services.dataset_service import DatasetService


class _FakeQuery:
    def __init__(self, items):  # noqa: ANN001
        self._items = list(items or [])

    def filter(self, *conds, **_kwargs):  # noqa: ANN001
        try:
            from sqlalchemy.sql import operators as sql_ops
            from sqlalchemy.sql.elements import BinaryExpression, BooleanClauseList
            from sqlalchemy.sql.operators import in_op
        except Exception:  # pragma: no cover
            return self

        def _cmp_value(v):  # noqa: ANN001
            if isinstance(v, uuid.UUID):
                return v.int
            return v

        def _matches(item, expr) -> bool:  # noqa: ANN001
            if isinstance(expr, BooleanClauseList):
                if expr.operator is sql_ops.and_:
                    return all(_matches(item, c) for c in expr.clauses)
                if expr.operator is sql_ops.or_:
                    return any(_matches(item, c) for c in expr.clauses)
                return True

            if not isinstance(expr, BinaryExpression):
                return True

            left_key = getattr(getattr(expr, "left", None), "key", None)
            if not left_key:
                return True
            left_val = getattr(item, str(left_key), None)
            right_val = getattr(getattr(expr, "right", None), "value", None)

            op = getattr(expr, "operator", None)
            if op is operator.eq:
                return _cmp_value(left_val) == _cmp_value(right_val)
            if op is operator.ne:
                return _cmp_value(left_val) != _cmp_value(right_val)
            if op is sql_ops.is_:
                return left_val is right_val
            if op is sql_ops.is_not:
                return left_val is not right_val
            if op is operator.gt:
                return _cmp_value(left_val) > _cmp_value(right_val)
            if op is operator.ge:
                return _cmp_value(left_val) >= _cmp_value(right_val)
            if op is operator.lt:
                return _cmp_value(left_val) < _cmp_value(right_val)
            if op is operator.le:
                return _cmp_value(left_val) <= _cmp_value(right_val)
            if op is in_op:
                if not isinstance(right_val, (list, tuple, set, frozenset)):
                    return False
                return _cmp_value(left_val) in {_cmp_value(v) for v in right_val}
            return True

        self._items = [it for it in self._items if all(_matches(it, c) for c in conds)]
        return self

    def count(self) -> int:  # noqa: ANN201
        return int(len(self._items))

    def all(self):  # noqa: ANN201
        return list(self._items)


class _FakeDB:
    def __init__(
        self,
        *,
        groups,
        group_members,
        datasets,
        dataset_member_perms,
        dataset_group_perms,
        documents,
        document_member_perms,
        document_group_perms,
    ):  # noqa: ANN001,E501
        self._data = {
            TenantGroup: list(groups or []),
            TenantGroupMember: list(group_members or []),
            Dataset: list(datasets or []),
            DatasetPermission: list(dataset_member_perms or []),
            DatasetGroupPermission: list(dataset_group_perms or []),
            Document: list(documents or []),
            DocumentPermission: list(document_member_perms or []),
            DocumentGroupPermission: list(document_group_perms or []),
        }

    def query(self, model):  # noqa: ANN001
        return _FakeQuery(self._data.get(model, []))


def _build_client(*, monkeypatch, role: str, db: _FakeDB, tenant_id: uuid.UUID):  # noqa: ANN001
    from app.api.v1.audit import router as audit_router

    class _Member:
        def __init__(self, role: str):
            self.role = role

    monkeypatch.setattr(DatasetService, "ensure_member", lambda *_a, **_k: _Member(role), raising=True)

    def _override_get_tenant_id() -> uuid.UUID:
        return tenant_id

    def _override_get_current_account_id() -> str:
        return "test-account"

    def _override_get_db():  # noqa: ANN202
        yield db

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = _override_get_tenant_id
    app.dependency_overrides[get_current_account_id] = _override_get_current_account_id
    app.include_router(audit_router, prefix="/api/v1/audit")
    return TestClient(app)


def test_access_graph_summary_denies_viewer(monkeypatch):  # noqa: ANN001
    tenant_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    db = _FakeDB(
        groups=[TenantGroup(id=uuid.uuid4(), tenant_id=tenant_id, name="g", created_at=now, updated_at=now)],
        group_members=[],
        datasets=[],
        dataset_member_perms=[],
        dataset_group_perms=[],
        documents=[],
        document_member_perms=[],
        document_group_perms=[],
    )
    client = _build_client(monkeypatch=monkeypatch, role="viewer", db=db, tenant_id=tenant_id)

    res = client.get("/api/v1/audit/access-graph/summary")
    assert res.status_code == 403, res.text


def test_access_graph_summary_includes_bounded_counts(monkeypatch):  # noqa: ANN001
    tenant_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    g1 = TenantGroup(id=uuid.uuid4(), tenant_id=tenant_id, name="finance", created_at=now, updated_at=now)
    g2 = TenantGroup(id=uuid.uuid4(), tenant_id=tenant_id, name="eng", created_at=now, updated_at=now)
    gm1 = TenantGroupMember(id=uuid.uuid4(), tenant_id=tenant_id, group_id=g1.id, user_id="alice", created_at=now)

    ds = Dataset(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        name="DS",
        description=None,
        permission=DatasetPermissionEnum.PARTIAL_MEMBERS,
        owner_id="owner",
        created_at=now,
        updated_at=now,
    )
    dperm = DatasetPermission(id=uuid.uuid4(), tenant_id=tenant_id, dataset_id=ds.id, account_id="bob", created_at=now)
    dgperm = DatasetGroupPermission(
        id=uuid.uuid4(), tenant_id=tenant_id, dataset_id=ds.id, group_id=g1.id, created_at=now
    )

    doc1 = Document(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        dataset_id=ds.id,
        filename="a.pdf",
        file_type="pdf",
        file_size=1,
        file_path="manual://a",
        owner_id="u1",
        access_mode=None,
        created_at=now,
        updated_at=now,
    )
    doc2 = Document(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        dataset_id=ds.id,
        filename="b.pdf",
        file_type="pdf",
        file_size=1,
        file_path="manual://b",
        owner_id="u2",
        access_mode="partial_members",
        created_at=now,
        updated_at=now,
    )
    doc_perm = DocumentPermission(
        id=uuid.uuid4(), tenant_id=tenant_id, document_id=doc2.id, account_id="bob", created_at=now
    )
    doc_gperm = DocumentGroupPermission(
        id=uuid.uuid4(), tenant_id=tenant_id, document_id=doc2.id, group_id=g1.id, created_at=now
    )

    db = _FakeDB(
        groups=[g1, g2],
        group_members=[gm1],
        datasets=[ds],
        dataset_member_perms=[dperm],
        dataset_group_perms=[dgperm],
        documents=[doc1, doc2],
        document_member_perms=[doc_perm],
        document_group_perms=[doc_gperm],
    )
    client = _build_client(monkeypatch=monkeypatch, role="auditor", db=db, tenant_id=tenant_id)

    res = client.get("/api/v1/audit/access-graph/summary")
    assert res.status_code == 200, res.text
    payload = res.json()
    assert payload.get("schema") == "mimirq.access_graph_summary.v1"
    assert payload.get("tenant_id") == str(tenant_id)

    assert payload.get("group_count") == 2
    assert payload.get("group_member_count") == 1

    assert payload.get("dataset_count") == 1
    perm_counts = payload.get("dataset_permission_counts") or {}
    assert perm_counts.get("partial_members") == 1

    assert payload.get("dataset_member_allowlist_count") == 1
    assert payload.get("dataset_group_allowlist_count") == 1

    assert payload.get("document_count") == 2
    doc_mode_counts = payload.get("document_access_mode_counts") or {}
    assert doc_mode_counts.get("inherit") == 1
    assert doc_mode_counts.get("partial_members") == 1

    assert payload.get("document_member_allowlist_count") == 1
    assert payload.get("document_group_allowlist_count") == 1

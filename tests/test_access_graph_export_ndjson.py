from __future__ import annotations

import gzip
import json
import operator
import uuid
from datetime import datetime, timedelta, timezone

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

    def order_by(self, *_args, **_kwargs):  # noqa: ANN001
        return self

    def limit(self, n: int):  # noqa: ANN001
        self._items = self._items[: int(n or 0)]
        return self

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


def _parse_ndjson(text: str) -> list[dict]:  # noqa: ANN001
    lines = [ln for ln in (text or "").splitlines() if ln.strip()]
    return [json.loads(ln) for ln in lines]


def test_access_graph_export_denies_viewer(monkeypatch):  # noqa: ANN001
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

    res = client.get("/api/v1/audit/access-graph/export?limit=10")
    assert res.status_code == 403, res.text


def test_access_graph_export_json_page_supports_cursor_and_is_pii_safe(monkeypatch):  # noqa: ANN001
    tenant_id = uuid.uuid4()
    t0 = datetime.now(timezone.utc)
    t1 = t0 + timedelta(seconds=1)
    t2 = t0 + timedelta(seconds=2)

    g1 = TenantGroup(id=uuid.UUID(int=1), tenant_id=tenant_id, name="finance", created_at=t0, updated_at=t0)
    g2 = TenantGroup(id=uuid.UUID(int=2), tenant_id=tenant_id, name="eng", created_at=t1, updated_at=t1)

    m1 = TenantGroupMember(
        id=uuid.UUID(int=3), tenant_id=tenant_id, group_id=g1.id, user_id="alice@example.com", created_at=t2
    )

    ds = Dataset(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        name="Secret Dataset",
        description=None,
        permission=DatasetPermissionEnum.PARTIAL_MEMBERS,
        owner_id="owner@example.com",
        created_at=t0,
        updated_at=t0,
    )

    doc = Document(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        dataset_id=ds.id,
        filename="top_secret.pdf",
        file_type="pdf",
        file_size=123,
        file_path="manual://x",
        owner_id="uploader@example.com",
        access_mode="partial_members",
        created_at=t0,
        updated_at=t0,
    )

    db = _FakeDB(
        groups=[g1, g2],
        group_members=[m1],
        datasets=[ds],
        dataset_member_perms=[],
        dataset_group_perms=[],
        documents=[doc],
        document_member_perms=[],
        document_group_perms=[],
    )
    client = _build_client(monkeypatch=monkeypatch, role="auditor", db=db, tenant_id=tenant_id)

    res0 = client.get("/api/v1/audit/access-graph/export?export_format=json&limit=2")
    assert res0.status_code == 200, res0.text
    payload0 = res0.json()
    assert payload0.get("schema") == "mimirq.access_graph_export_page.v1"
    assert payload0.get("returned") == 2
    assert payload0.get("next_cursor")
    items0 = payload0.get("items") or []
    assert all(it.get("schema") == "mimirq.access_graph_export_record.v1" for it in items0)

    # Default PII-safe: raw user ids should be omitted.
    for it in items0:
        if it.get("kind") in {"group_member", "dataset", "document"}:
            assert it.get("user_id") is None
            assert it.get("account_id") is None
            assert it.get("owner_id") is None

    cursor = payload0["next_cursor"]
    res1 = client.get(
        f"/api/v1/audit/access-graph/export?export_format=json&limit=10"
        f"&after_kind={cursor['after_kind']}&after_created_at={cursor['after_created_at']}&after_id={cursor['after_id']}"
    )
    assert res1.status_code == 200, res1.text
    payload1 = res1.json()
    assert payload1.get("schema") == "mimirq.access_graph_export_page.v1"
    assert payload1.get("returned") >= 1

    # Ensure no document content leaks.
    dumped = json.dumps(payload1, ensure_ascii=False)
    assert "top_secret.pdf" not in dumped


def test_access_graph_export_ndjson_supports_gzip(monkeypatch):  # noqa: ANN001
    tenant_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    g1 = TenantGroup(id=uuid.uuid4(), tenant_id=tenant_id, name="g", created_at=now, updated_at=now)
    db = _FakeDB(
        groups=[g1],
        group_members=[],
        datasets=[],
        dataset_member_perms=[],
        dataset_group_perms=[],
        documents=[],
        document_member_perms=[],
        document_group_perms=[],
    )
    client = _build_client(monkeypatch=monkeypatch, role="auditor", db=db, tenant_id=tenant_id)

    res = client.get("/api/v1/audit/access-graph/export?limit=10&gzip=true")
    assert res.status_code == 200, res.text
    assert str(res.headers.get("content-encoding") or "").lower() == "gzip"

    raw = res.content
    try:
        text = raw.decode("utf-8")
        if not text.lstrip().startswith("{"):
            text = gzip.decompress(raw).decode("utf-8")
    except UnicodeDecodeError:
        text = gzip.decompress(raw).decode("utf-8")

    got = _parse_ndjson(text)
    assert got and got[0].get("schema") == "mimirq.access_graph_export_record.v1"

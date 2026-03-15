from __future__ import annotations

import gzip
import json
import operator
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.core.database import get_db
from app.models.audit_log import AuditLog
from app.services.dataset_service import DatasetService


class _FakeQuery:
    def __init__(self, items):  # noqa: ANN001
        self._items = list(items or [])

    def filter(self, *conds, **_kwargs):  # noqa: ANN001,D401
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

        items = [it for it in self._items if all(_matches(it, c) for c in conds)]
        self._items = items
        return self

    def order_by(self, *_args, **_kwargs):  # noqa: ANN001,D401
        return self

    def limit(self, n: int):  # noqa: D401
        self._items = self._items[: int(n or 0)]
        return self

    def all(self):  # noqa: D401
        return list(self._items)


class _FakeDB:
    def __init__(self, items):  # noqa: ANN001
        self._items = list(items or [])

    def query(self, _model):  # noqa: ANN001
        return _FakeQuery(self._items)


def _build_client(*, monkeypatch, items, role: str):  # noqa: ANN001
    import app.api.v1.audit as audit_mod
    from app.api.v1.audit import export_audit_logs

    class _Member:
        def __init__(self, role: str):
            self.role = role

    monkeypatch.setattr(DatasetService, "ensure_member", lambda *_a, **_k: _Member(role), raising=True)

    tenant_id = items[0].tenant_id if items else uuid.uuid4()

    def _override_get_tenant_id() -> uuid.UUID:
        return tenant_id

    def _override_get_current_account_id() -> str:
        return "test-account"

    def _override_get_db():  # noqa: ANN202
        yield _FakeDB(items)

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = _override_get_tenant_id
    app.dependency_overrides[get_current_account_id] = _override_get_current_account_id
    app.get("/api/v1/audit/logs/export")(export_audit_logs)
    client = TestClient(app)
    return client, audit_mod


def _parse_ndjson(text: str) -> list[dict]:  # noqa: ANN001
    lines = [ln for ln in (text or "").splitlines() if ln.strip()]
    return [json.loads(ln) for ln in lines]


def test_audit_export_ndjson_sanitizes_sensitive_details_by_default(monkeypatch):  # noqa: ANN001
    tenant_id = uuid.uuid4()
    now = datetime.now(UTC)
    item = AuditLog(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        actor_id="u1",
        action="test",
        details={"sql": "SELECT 1", "ok": True},
        created_at=now,
    )

    client, _mod = _build_client(monkeypatch=monkeypatch, items=[item], role="auditor")

    res = client.get("/api/v1/audit/logs/export?limit=10")
    assert res.status_code == 200, res.text
    body = _parse_ndjson(res.text)
    assert len(body) == 1
    assert body[0].get("action") == "test"
    details = body[0].get("details") or {}
    assert "ok" in details
    assert "sql" not in details


def test_audit_export_ndjson_can_include_sensitive_details_when_requested(monkeypatch):  # noqa: ANN001
    tenant_id = uuid.uuid4()
    now = datetime.now(UTC)
    item = AuditLog(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        actor_id="u1",
        action="test",
        details={"sql": "SELECT 1", "ok": True},
        created_at=now,
    )

    client, _mod = _build_client(monkeypatch=monkeypatch, items=[item], role="auditor")

    res = client.get("/api/v1/audit/logs/export?limit=10&include_sensitive=true")
    assert res.status_code == 200, res.text
    body = _parse_ndjson(res.text)
    assert len(body) == 1
    details = body[0].get("details") or {}
    assert details.get("sql") == "SELECT 1"


def test_audit_export_ndjson_supports_cursor(monkeypatch):  # noqa: ANN001
    tenant_id = uuid.uuid4()
    t0 = datetime.now(UTC)
    t1 = t0 + timedelta(seconds=1)
    t2 = t0 + timedelta(seconds=2)

    items = [
        AuditLog(id=uuid.UUID(int=1), tenant_id=tenant_id, action="a", details={}, created_at=t0),
        AuditLog(id=uuid.UUID(int=2), tenant_id=tenant_id, action="b", details={}, created_at=t1),
        AuditLog(id=uuid.UUID(int=3), tenant_id=tenant_id, action="c", details={}, created_at=t2),
    ]

    client, _mod = _build_client(monkeypatch=monkeypatch, items=items, role="auditor")

    res0 = client.get("/api/v1/audit/logs/export?limit=2")
    assert res0.status_code == 200, res0.text
    got0 = _parse_ndjson(res0.text)
    assert [r.get("action") for r in got0] == ["a", "b"]

    after_created_at = got0[-1]["created_at"]
    after_id = got0[-1]["id"]
    res1 = client.get(
        f"/api/v1/audit/logs/export?limit=10&after_created_at={after_created_at}&after_id={after_id}"
    )
    assert res1.status_code == 200, res1.text
    got1 = _parse_ndjson(res1.text)
    assert [r.get("action") for r in got1] == ["c"]


def test_audit_export_ndjson_denies_viewer(monkeypatch):  # noqa: ANN001
    tenant_id = uuid.uuid4()
    now = datetime.now(UTC)
    item = AuditLog(id=uuid.uuid4(), tenant_id=tenant_id, action="test", details={}, created_at=now)

    client, _mod = _build_client(monkeypatch=monkeypatch, items=[item], role="viewer")

    res = client.get("/api/v1/audit/logs/export?limit=10")
    assert res.status_code == 403, res.text


def test_audit_export_ndjson_supports_gzip(monkeypatch):  # noqa: ANN001
    tenant_id = uuid.uuid4()
    now = datetime.now(UTC)
    item = AuditLog(id=uuid.uuid4(), tenant_id=tenant_id, action="test", details={}, created_at=now)

    client, _mod = _build_client(monkeypatch=monkeypatch, items=[item], role="auditor")

    res = client.get("/api/v1/audit/logs/export?limit=10&gzip=true")
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
    assert [r.get("action") for r in got] == ["test"]


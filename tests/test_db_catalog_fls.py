from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.core.database import get_db


class _FakeQuery:
    def __init__(self, items):  # noqa: ANN001
        self._items = list(items or [])

    def filter(self, *args, **kwargs):  # noqa: ANN001,D401
        # Minimal SQLAlchemy filter emulation for unit tests (supports == and IN).
        try:
            from sqlalchemy.sql.elements import BinaryExpression
        except Exception:  # pragma: no cover
            return self

        items = list(self._items)
        for cond in args:
            if not isinstance(cond, BinaryExpression):
                continue
            key = getattr(getattr(cond, "left", None), "key", None)
            val = getattr(getattr(cond, "right", None), "value", None)
            if not key:
                continue
            if isinstance(val, (list, tuple, set)):
                items = [d for d in items if getattr(d, key, None) in val]
            elif val is not None:
                items = [d for d in items if getattr(d, key, None) == val]

        self._items = items
        return self

    def order_by(self, *args, **kwargs):  # noqa: ANN001,D401
        return self

    def all(self):  # noqa: D401
        return list(self._items)

    def first(self):  # noqa: D401
        return self._items[0] if self._items else None


class _FakeDB:
    def __init__(self, tables, columns):  # noqa: ANN001
        self._tables = list(tables or [])
        self._columns = list(columns or [])

    def query(self, model):  # noqa: ANN001
        from app.models.db_catalog import DbCatalogColumn, DbCatalogTable

        if model is DbCatalogTable:
            return _FakeQuery(self._tables)
        if model is DbCatalogColumn:
            return _FakeQuery(self._columns)
        return _FakeQuery([])


def _override_get_db(db_obj):  # noqa: ANN001
    def _gen():  # noqa: ANN202
        yield db_obj

    return _gen


def _override_get_current_account_id() -> str:
    return "test-account"


def test_db_catalog_fls_masks_denied_columns(monkeypatch):  # noqa: ANN001
    from app.api.v1.db_catalog import get_db_catalog_table
    from app.services.dataset_service import DatasetService

    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    table_id = uuid.uuid4()

    class _Dataset:
        def __init__(self) -> None:
            self.id = dataset_id
            self.tenant_id = tenant_id
            self.name = "Demo"
            self.dataset_metadata = {
                "fls_policy": {
                    "version": "1",
                    "rules": [
                        {
                            "id": "r1",
                            "name": "Mask SSN column metadata",
                            "enabled": True,
                            "sources": ["db_catalog"],
                            "column_name_regex": "^ssn$",
                            "allow_roles": ["owner"],
                            "allow_account_ids": [],
                            "mask": "[MASK]",
                        }
                    ],
                }
            }

    ds = _Dataset()

    class _Table:
        def __init__(self) -> None:
            self.id = table_id
            self.tenant_id = tenant_id
            self.dataset_id = dataset_id
            self.connector_config_id = None
            self.engine = "mysql"
            self.db_name = "db"
            self.schema_name = "public"
            self.table_name = "t"
            self.table_type = "table"
            self.comment = None
            self.fingerprint = "fp"
            self.last_seen_at = None
            self.created_at = datetime.now(UTC)
            self.updated_at = datetime.now(UTC)

    table = _Table()

    class _Col:
        def __init__(self, *, cid, name, ordinal, comment):  # noqa: ANN001
            self.id = cid
            self.table_id = table_id
            self.ordinal = ordinal
            self.name = name
            self.data_type = "text"
            self.nullable = True
            self.comment = comment
            self.created_at = datetime.now(UTC)

    col_ssn = _Col(cid=uuid.uuid4(), name="ssn", ordinal=1, comment="Sensitive")
    col_name = _Col(cid=uuid.uuid4(), name="name", ordinal=2, comment="Non-sensitive")

    # Dataset access: allow.
    monkeypatch.setattr(DatasetService, "get_dataset", lambda _db, _tid, _did: ds, raising=True)
    monkeypatch.setattr(DatasetService, "assert_dataset_readable", lambda _db, _dataset, _account_id: None, raising=True)

    class _Member:
        role = "member"

    class _Owner:
        role = "owner"

    monkeypatch.setattr(DatasetService, "ensure_member", lambda _db, _tid, _aid: _Member(), raising=True)

    import app.api.v1.db_catalog as mod

    events: list[str] = []

    def _fake_audit_log_event(_db, **kwargs):  # noqa: ANN001
        events.append(str(kwargs.get("action") or ""))

    monkeypatch.setattr(mod, "audit_log_event", _fake_audit_log_event, raising=True)

    db = _FakeDB([table], [col_ssn, col_name])

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db(db)
    app.dependency_overrides[get_tenant_id] = lambda: tenant_id
    app.dependency_overrides[get_current_account_id] = _override_get_current_account_id

    app.get("/api/v1/datasets/{dataset_id}/db-catalog/tables/{table_id}")(get_db_catalog_table)
    client = TestClient(app)

    # Non-owner: masked column name + comment.
    res = client.get(f"/api/v1/datasets/{dataset_id}/db-catalog/tables/{table_id}")
    assert res.status_code == 200
    payload = res.json()
    cols = payload["columns"]
    assert any(c["name"] == "[MASK]" and c["comment"] == "[MASK]" for c in cols)
    assert any(c["name"] == "name" and c["comment"] == "Non-sensitive" for c in cols)
    assert "fls.redaction_applied" in events

    # Owner: raw values.
    events.clear()
    monkeypatch.setattr(DatasetService, "ensure_member", lambda _db, _tid, _aid: _Owner(), raising=True)

    res = client.get(f"/api/v1/datasets/{dataset_id}/db-catalog/tables/{table_id}")
    assert res.status_code == 200
    payload = res.json()
    cols = payload["columns"]
    assert any(c["name"] == "ssn" and c["comment"] == "Sensitive" for c in cols)
    assert "fls.redaction_applied" not in events


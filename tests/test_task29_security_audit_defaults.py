from __future__ import annotations

import uuid
from datetime import datetime, timezone

from app.models.connector import ConnectorRun
from app.models.connector_config import ConnectorConfig


class _FakeQuery:
    def __init__(self, items):  # noqa: ANN001
        self._items = list(items or [])

    def filter(self, *args, **kwargs):  # noqa: ANN001,D401
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

    def first(self):  # noqa: D401
        return self._items[0] if self._items else None


class _FakeDB:
    def __init__(self, docs=None):  # noqa: ANN001
        self._docs = list(docs or [])

    def query(self, _model):  # noqa: ANN001
        return _FakeQuery(self._docs)


def test_redact_sql_literals_masks_strings_and_long_numbers():
    from app.services.security_redaction import redact_sql_literals

    sql = "SELECT * FROM t WHERE name='Alice''s' AND token='abc123' AND account_id=123456 AND small=42"
    out = redact_sql_literals(sql)

    assert "'<redacted>'" in out
    assert "<redacted_num>" in out
    assert "small=42" in out
    assert "abc123" not in out


def test_redact_connection_info_masks_db_fields_when_enabled():
    from app.services.security_redaction import redact_connection_info

    cfg = {
        "host": "db.internal",
        "port": 3306,
        "database": "demo",
        "username": "svc",
        "password": "<redacted>",
        "dsn": "mysql://svc:secret@db.internal:3306/demo",
        "nested": {"uri": "postgres://x:y@h:5432/z"},
    }
    out = redact_connection_info(cfg, enabled=True)

    assert out["host"] == "<redacted_conn>"
    assert out["port"] == "<redacted_conn>"
    assert out["database"] == "<redacted_conn>"
    assert out["username"] == "<redacted_conn>"
    assert out["dsn"] == "<redacted_conn>"
    assert out["nested"]["uri"] == "<redacted_conn>"
    assert out["password"] == "<redacted>"


def test_audit_ensure_admin_allows_auditor(monkeypatch):  # noqa: ANN001
    import app.api.v1.audit as audit_mod
    from app.services.dataset_service import DatasetService

    class _Member:
        role = "auditor"

    monkeypatch.setattr(DatasetService, "ensure_member", lambda *args, **kwargs: _Member(), raising=True)
    audit_mod._ensure_admin(db=object(), tenant_id=uuid.uuid4(), account_id="u")


def test_audit_ensure_admin_rejects_non_admin(monkeypatch):  # noqa: ANN001
    from fastapi import HTTPException

    import app.api.v1.audit as audit_mod
    from app.services.dataset_service import DatasetService

    class _Member:
        role = "viewer"

    monkeypatch.setattr(DatasetService, "ensure_member", lambda *args, **kwargs: _Member(), raising=True)
    try:
        audit_mod._ensure_admin(db=object(), tenant_id=uuid.uuid4(), account_id="u")
    except HTTPException as exc:
        assert exc.status_code == 403
    else:  # pragma: no cover
        raise AssertionError("expected HTTPException")


def test_query_dataset_table_hides_sql_by_default_and_allows_privileged_include(monkeypatch):  # noqa: ANN001
    import app.api.v1.dataset_tables as mod
    from app.api.schemas.table_store import TableQueryRequest

    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    table_id = f"doc:{uuid.uuid4()}:sheet:0"

    class _Dataset:
        def __init__(self) -> None:
            self.id = dataset_id
            self.tenant_id = tenant_id

    class _Member:
        role = "auditor"

    monkeypatch.setattr(mod.DatasetService, "get_dataset", lambda *args, **kwargs: _Dataset(), raising=True)
    monkeypatch.setattr(mod.DatasetService, "assert_dataset_readable", lambda *args, **kwargs: None, raising=True)
    monkeypatch.setattr(mod.DatasetService, "ensure_member", lambda *args, **kwargs: _Member(), raising=True)
    monkeypatch.setattr(mod, "filter_allowed_document_ids", lambda *args, **kwargs: None, raising=True)
    monkeypatch.setattr(
        mod,
        "run_table_query",
        lambda **kwargs: {
            "sql": kwargs.get("sql") or "",
            "columns": ["a"],
            "rows": [[1]],
            "truncated": False,
        },
        raising=True,
    )

    body = TableQueryRequest(sql="SELECT * FROM t WHERE name='alice' AND account_id=123456")
    hidden = mod.query_dataset_table(
        dataset_id=dataset_id,
        table_id=table_id,
        body=body,
        include_sql=False,
        tenant_id=tenant_id,
        account_id="u",
        db=_FakeDB(),
    )
    assert hidden.sql == "<hidden>"

    shown = mod.query_dataset_table(
        dataset_id=dataset_id,
        table_id=table_id,
        body=body,
        include_sql=True,
        tenant_id=tenant_id,
        account_id="u",
        db=_FakeDB(),
    )
    assert shown.sql != "<hidden>"
    assert "<redacted_num>" in shown.sql
    assert "'<redacted>'" in shown.sql


def test_connector_outputs_mask_db_connection_info():
    import app.api.v1.connectors as connectors_mod

    now = datetime.now(timezone.utc)
    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    run = ConnectorRun(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        connector_id="mysql_catalog",
        requested_by="u",
        status="pending",
        config={
            "host": "db.internal",
            "port": 3306,
            "database": "demo",
            "username": "svc",
            "password": "secret",
            "dsn": "mysql://svc:secret@db.internal:3306/demo",
        },
        stats={},
        created_at=now,
    )
    run.documents = []
    run_out = connectors_mod._run_out(run)
    assert run_out.config["password"] == "<redacted>"
    assert run_out.config["host"] == "<redacted_conn>"
    assert run_out.config["port"] == "<redacted_conn>"
    assert run_out.config["database"] == "<redacted_conn>"
    assert run_out.config["username"] == "<redacted_conn>"
    assert run_out.config["dsn"] == "<redacted_conn>"

    cfg = ConnectorConfig(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        connector_id="sqlserver_catalog",
        name="demo",
        enabled=True,
        config={
            "host": "db.internal",
            "port": 1433,
            "database": "demo",
            "username": "svc",
            "password": "secret",
            "connection_string": "Server=db.internal;Database=demo",
        },
        state={},
        created_at=now,
        updated_at=now,
    )
    cfg_out = connectors_mod._config_out(cfg)
    assert cfg_out.config["password"] == "<redacted>"
    assert cfg_out.config["host"] == "<redacted_conn>"
    assert cfg_out.config["port"] == "<redacted_conn>"
    assert cfg_out.config["database"] == "<redacted_conn>"
    assert cfg_out.config["username"] == "<redacted_conn>"
    assert cfg_out.config["connection_string"] == "<redacted_conn>"

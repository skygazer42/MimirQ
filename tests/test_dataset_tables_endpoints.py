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
        self._offset = 0
        self._limit = None

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

    def offset(self, n: int):  # noqa: D401
        self._offset = int(n or 0)
        return self

    def limit(self, n: int):  # noqa: D401
        self._limit = int(n or 0)
        return self

    def all(self):  # noqa: D401
        if self._limit is None or self._limit <= 0:
            return self._items[self._offset :]
        return self._items[self._offset : self._offset + self._limit]

    def first(self):  # noqa: D401
        items = self.all()
        return items[0] if items else None


class _FakeDB:
    def __init__(self, docs):  # noqa: ANN001
        self._docs = list(docs or [])

    def query(self, _model):  # noqa: ANN001
        return _FakeQuery(self._docs)


def _override_get_db(docs):  # noqa: ANN001
    def _gen():  # noqa: ANN202
        yield _FakeDB(docs)

    return _gen


def _override_get_tenant_id() -> uuid.UUID:
    return uuid.uuid4()


def _override_get_current_account_id() -> str:
    return "test-account"


def test_dataset_tables_list_and_get(monkeypatch):  # noqa: ANN001
    from app.api.v1.dataset_tables import (
        ask_dataset_table,
        get_dataset_table,
        list_dataset_tables,
        preview_dataset_table,
        query_dataset_table,
    )
    from app.services.dataset_service import DatasetService

    dataset_id = uuid.uuid4()
    doc_id = uuid.uuid4()
    table_id = f"doc:{doc_id}:sheet:0"

    class _Dataset:
        def __init__(self) -> None:
            self.id = dataset_id
            self.tenant_id = uuid.uuid4()
            self.name = "Demo"
            self.dataset_metadata = {}

    ds = _Dataset()

    class _Doc:
        def __init__(self) -> None:
            self.id = doc_id
            self.tenant_id = ds.tenant_id
            self.dataset_id = dataset_id
            self.filename = "demo.docx"
            self.file_type = "docx"
            self.status = "completed"
            self.updated_at = datetime.now(UTC)
            self.doc_metadata = {
                "table_store": {
                    "version": "1",
                    "tables": [
                        {
                            "table_id": table_id,
                            "sheet_index": 0,
                            "sheet_name": "Sheet1",
                            "row_count": 2,
                            "col_count": 2,
                            "truncated": False,
                            "columns": [{"name": "a", "dtype": "int"}, {"name": "b", "dtype": "int"}],
                            "sample_rows": [{"a": 1, "b": 2}],
                        }
                    ],
                }
            }

    doc = _Doc()

    # Dataset access: allow.
    monkeypatch.setattr(DatasetService, "get_dataset", lambda _db, _tenant_id, _did: ds, raising=True)
    monkeypatch.setattr(DatasetService, "assert_dataset_readable", lambda _db, _dataset, _account_id: None, raising=True)

    class _Member:
        role = "owner"

    monkeypatch.setattr(DatasetService, "ensure_member", lambda _db, _tenant_id, _account_id: _Member(), raising=True)

    # Doc ACL: allow.
    import app.api.v1.dataset_tables as mod

    monkeypatch.setattr(mod, "filter_allowed_document_ids", lambda _db, _tenant_id, _account_id, doc_ids: doc_ids, raising=True)
    monkeypatch.setattr(mod, "get_allowed_document_id_sets", lambda _db, _tenant_id, _account_id, doc_ids, _check_member=False: (set(doc_ids), set()), raising=True)

    # Query executor: stub.
    monkeypatch.setattr(
        mod,
        "run_table_query",
        lambda **kwargs: {
            "sql": kwargs.get("sql") or "",
            "columns": ["a", "b"],
            "rows": [[1, 2]],
            "truncated": False,
            "planner_execution_mismatch": {
                "mismatch": False,
                "reasons": [],
                "expected_sql_fingerprint": "fp1234abcd",
                "actual_sql_fingerprint": "fp1234abcd",
                "expected_tables": ["sheet_0"],
                "actual_tables": ["sheet_0"],
            },
        },
        raising=True,
    )

    # TAG: stub LLM helpers (avoid real network).
    monkeypatch.setattr(mod, "tag_enabled", lambda: True, raising=True)
    monkeypatch.setattr(mod, "generate_sql_for_table", lambda **_kwargs: 'SELECT * FROM "sheet_0" LIMIT 10', raising=True)
    monkeypatch.setattr(
        mod,
        "generate_sql_for_table_with_metadata",
        lambda **_kwargs: (
            'SELECT * FROM "sheet_0" LIMIT 10',
            "llm",
            {
                "schema_link": {
                    "score": 0.66,
                    "strategy": "column_overlap",
                    "reason": "matched_columns",
                    "matched_columns": ["a", "b"],
                    "matched_values": [],
                    "matched_tables": ["sheet_0"],
                },
                "planner": {"strategy": "deterministic_heuristic", "reason": "projection"},
                "sql_fingerprint": "fp1234abcd",
                "join_provenance": [
                    {
                        "left_table": "sheet_0",
                        "left_column": "a",
                        "right_table": "sheet_0",
                        "right_column": "a",
                        "confidence": 1.0,
                        "reason": "single_table",
                    }
                ],
            },
        ),
        raising=False,
    )
    monkeypatch.setattr(mod, "generate_answer_from_result", lambda **_kwargs: "answer", raising=True)

    # Enable NL2SQL flag checks in endpoint.
    from app.core.config import settings

    monkeypatch.setattr(settings, "TABLE_NL2SQL_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "LLM_API_KEY", "test", raising=False)
    monkeypatch.setattr(settings, "TABLE_LLM_ALLOW_RESULT_EGRESS", True, raising=False)

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db([doc])
    app.dependency_overrides[get_tenant_id] = lambda: ds.tenant_id
    app.dependency_overrides[get_current_account_id] = _override_get_current_account_id

    app.get("/api/v1/datasets/{dataset_id}/tables")(list_dataset_tables)
    app.get("/api/v1/datasets/{dataset_id}/tables/{table_id}")(get_dataset_table)
    app.get("/api/v1/datasets/{dataset_id}/tables/{table_id}/preview")(preview_dataset_table)
    app.post("/api/v1/datasets/{dataset_id}/tables/{table_id}/query")(query_dataset_table)
    app.post("/api/v1/datasets/{dataset_id}/tables/{table_id}/ask")(ask_dataset_table)

    client = TestClient(app)

    res = client.get(f"/api/v1/datasets/{dataset_id}/tables")
    assert res.status_code == 200
    payload = res.json()
    assert payload["total"] == 1
    assert payload["items"][0]["table_id"] == table_id

    res = client.get(f"/api/v1/datasets/{dataset_id}/tables/{table_id}")
    assert res.status_code == 200
    assert res.json()["table_id"] == table_id

    res = client.get(f"/api/v1/datasets/{dataset_id}/tables/{table_id}/preview")
    assert res.status_code == 200
    assert res.json()["columns"] == ["a", "b"]

    res = client.post(f"/api/v1/datasets/{dataset_id}/tables/{table_id}/query", json={"sql": 'SELECT * FROM "sheet_0" LIMIT 1'})
    assert res.status_code == 200
    assert res.json()["rows"] == [[1, 2]]

    res = client.post(f"/api/v1/datasets/{dataset_id}/tables/{table_id}/ask", json={"question": "What is a+b?"})
    assert res.status_code == 200
    ask_payload = res.json()
    assert ask_payload["answer"] == "answer"
    assert ask_payload["sql_generation_mode"] == "llm"
    assert float((ask_payload.get("schema_link_diagnostics") or {}).get("score") or 0.0) > 0.0
    assert str((ask_payload.get("planner_diagnostics") or {}).get("strategy") or "")
    assert isinstance(ask_payload.get("join_provenance"), list)
    assert str(ask_payload.get("sql_fingerprint") or "") == "fp1234abcd"
    assert bool((ask_payload.get("planner_execution_mismatch") or {}).get("mismatch")) is False


def test_dataset_tables_row_redaction_guard(monkeypatch):  # noqa: ANN001
    """
    Enterprise guard: when TABLE_ROW_REDACTION_ENABLED=true, redact common PII/secrets from
    sample rows and query results for non-admin roles.
    """
    from app.api.v1.dataset_tables import get_dataset_table, query_dataset_table
    from app.services.dataset_service import DatasetService

    dataset_id = uuid.uuid4()
    doc_id = uuid.uuid4()
    table_id = f"doc:{doc_id}:sheet:0"

    class _Dataset:
        def __init__(self) -> None:
            self.id = dataset_id
            self.tenant_id = uuid.uuid4()
            self.name = "Demo"
            self.dataset_metadata = {}

    ds = _Dataset()

    class _Doc:
        def __init__(self) -> None:
            self.id = doc_id
            self.tenant_id = ds.tenant_id
            self.dataset_id = dataset_id
            self.filename = "demo.xlsx"
            self.file_type = "xlsx"
            self.status = "completed"
            self.updated_at = datetime.now(UTC)
            self.doc_metadata = {
                "table_store": {
                    "version": "1",
                    "tables": [
                        {
                            "table_id": table_id,
                            "sheet_index": 0,
                            "sheet_name": "Sheet1",
                            "row_count": 1,
                            "col_count": 2,
                            "truncated": False,
                            "columns": [{"name": "email", "dtype": "text"}, {"name": "token", "dtype": "text"}],
                            "sample_rows": [
                                {
                                    "email": "alice@example.com",
                                    "token": "sk-1234567890abcdef1234567890",
                                }
                            ],
                        }
                    ],
                }
            }

    doc = _Doc()

    # Dataset access: allow.
    monkeypatch.setattr(DatasetService, "get_dataset", lambda _db, _tenant_id, _did: ds, raising=True)
    monkeypatch.setattr(DatasetService, "assert_dataset_readable", lambda _db, _dataset, _account_id: None, raising=True)

    import app.api.v1.dataset_tables as mod

    # Doc ACL: allow.
    monkeypatch.setattr(mod, "filter_allowed_document_ids", lambda _db, _tenant_id, _account_id, doc_ids: doc_ids, raising=True)
    monkeypatch.setattr(mod, "get_allowed_document_id_sets", lambda _db, _tenant_id, _account_id, doc_ids, _check_member=False: (set(doc_ids), set()), raising=True)

    # Query executor: return sensitive strings.
    monkeypatch.setattr(
        mod,
        "run_table_query",
        lambda **kwargs: {"sql": kwargs.get("sql") or "", "columns": ["email", "token"], "rows": [["alice@example.com", "sk-1234567890abcdef1234567890"]], "truncated": False},
        raising=True,
    )

    from app.core.config import settings

    monkeypatch.setattr(settings, "TABLE_ROW_REDACTION_ENABLED", True, raising=False)

    class _Member:
        role = "member"

    class _Owner:
        role = "owner"

    # Non-admin: redacted.
    monkeypatch.setattr(DatasetService, "ensure_member", lambda _db, _tenant_id, _account_id: _Member(), raising=True)

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db([doc])
    app.dependency_overrides[get_tenant_id] = lambda: ds.tenant_id
    app.dependency_overrides[get_current_account_id] = _override_get_current_account_id

    app.get("/api/v1/datasets/{dataset_id}/tables/{table_id}")(get_dataset_table)
    app.post("/api/v1/datasets/{dataset_id}/tables/{table_id}/query")(query_dataset_table)

    client = TestClient(app)

    res = client.get(f"/api/v1/datasets/{dataset_id}/tables/{table_id}")
    assert res.status_code == 200
    got = res.json()
    assert got["sample_rows"][0]["email"] == "[REDACTED]"
    assert got["sample_rows"][0]["token"] == "[SECRET]"

    res = client.post(f"/api/v1/datasets/{dataset_id}/tables/{table_id}/query", json={"sql": 'SELECT * FROM "sheet_0" LIMIT 1'})
    assert res.status_code == 200
    got = res.json()
    assert got["rows"][0][0] == "[REDACTED]"
    assert got["rows"][0][1] == "[SECRET]"

    # Admin: raw values.
    monkeypatch.setattr(DatasetService, "ensure_member", lambda _db, _tenant_id, _account_id: _Owner(), raising=True)

    res = client.get(f"/api/v1/datasets/{dataset_id}/tables/{table_id}")
    assert res.status_code == 200
    got = res.json()
    assert got["sample_rows"][0]["email"] == "alice@example.com"
    assert got["sample_rows"][0]["token"] == "sk-1234567890abcdef1234567890"


def test_dataset_tables_fls_masks_sample_rows_and_query_rows(monkeypatch):  # noqa: ANN001
    """
    Enterprise FLS: mask denied columns by role (preserve response shape; only values change).
    """
    from app.api.v1.dataset_tables import get_dataset_table, query_dataset_table
    from app.services.dataset_service import DatasetService

    dataset_id = uuid.uuid4()
    doc_id = uuid.uuid4()
    table_id = f"doc:{doc_id}:sheet:0"

    class _Dataset:
        def __init__(self) -> None:
            self.id = dataset_id
            self.tenant_id = uuid.uuid4()
            self.name = "Demo"
            self.dataset_metadata = {
                "fls_policy": {
                    "version": "1",
                    "rules": [
                        {
                            "id": "r1",
                            "name": "Mask SSN",
                            "enabled": True,
                            "sources": ["table_store"],
                            "column_name_regex": "^ssn$",
                            "allow_roles": ["owner"],
                            "allow_account_ids": [],
                            "mask": "[FLS]",
                        }
                    ],
                }
            }

    ds = _Dataset()

    class _Doc:
        def __init__(self) -> None:
            self.id = doc_id
            self.tenant_id = ds.tenant_id
            self.dataset_id = dataset_id
            self.filename = "demo.xlsx"
            self.file_type = "xlsx"
            self.status = "completed"
            self.updated_at = datetime.now(UTC)
            self.doc_metadata = {
                "table_store": {
                    "version": "1",
                    "tables": [
                        {
                            "table_id": table_id,
                            "sheet_index": 0,
                            "sheet_name": "Sheet1",
                            "row_count": 1,
                            "col_count": 2,
                            "truncated": False,
                            "columns": [{"name": "ssn", "dtype": "text"}, {"name": "name", "dtype": "text"}],
                            "sample_rows": [{"ssn": "123-45-6789", "name": "Alice"}],
                        }
                    ],
                }
            }

    doc = _Doc()

    # Dataset access: allow.
    monkeypatch.setattr(DatasetService, "get_dataset", lambda _db, _tenant_id, _did: ds, raising=True)
    monkeypatch.setattr(DatasetService, "assert_dataset_readable", lambda _db, _dataset, _account_id: None, raising=True)

    import app.api.v1.dataset_tables as mod

    # Doc ACL: allow.
    monkeypatch.setattr(mod, "filter_allowed_document_ids", lambda _db, _tenant_id, _account_id, doc_ids: doc_ids, raising=True)
    monkeypatch.setattr(mod, "get_allowed_document_id_sets", lambda _db, _tenant_id, _account_id, doc_ids, _check_member=False: (set(doc_ids), set()), raising=True)

    # Query executor: return sensitive values.
    monkeypatch.setattr(
        mod,
        "run_table_query",
        lambda **kwargs: {"sql": kwargs.get("sql") or "", "columns": ["ssn", "name"], "rows": [["123-45-6789", "Alice"]], "truncated": False},
        raising=True,
    )

    from app.core.config import settings

    monkeypatch.setattr(settings, "TABLE_ROW_REDACTION_ENABLED", False, raising=False)

    class _Member:
        role = "member"

    class _Owner:
        role = "owner"

    # Non-owner role: masked.
    monkeypatch.setattr(DatasetService, "ensure_member", lambda _db, _tenant_id, _account_id: _Member(), raising=True)

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db([doc])
    app.dependency_overrides[get_tenant_id] = lambda: ds.tenant_id
    app.dependency_overrides[get_current_account_id] = _override_get_current_account_id

    app.get("/api/v1/datasets/{dataset_id}/tables/{table_id}")(get_dataset_table)
    app.post("/api/v1/datasets/{dataset_id}/tables/{table_id}/query")(query_dataset_table)

    client = TestClient(app)

    res = client.get(f"/api/v1/datasets/{dataset_id}/tables/{table_id}")
    assert res.status_code == 200
    got = res.json()
    assert got["sample_rows"][0]["ssn"] == "[FLS]"
    assert got["sample_rows"][0]["name"] == "Alice"

    res = client.post(f"/api/v1/datasets/{dataset_id}/tables/{table_id}/query", json={"sql": 'SELECT * FROM "sheet_0" LIMIT 1'})
    assert res.status_code == 200
    got = res.json()
    assert got["rows"][0][0] == "[FLS]"
    assert got["rows"][0][1] == "Alice"

    # Owner role: raw.
    monkeypatch.setattr(DatasetService, "ensure_member", lambda _db, _tenant_id, _account_id: _Owner(), raising=True)

    res = client.get(f"/api/v1/datasets/{dataset_id}/tables/{table_id}")
    assert res.status_code == 200
    got = res.json()
    assert got["sample_rows"][0]["ssn"] == "123-45-6789"
    assert got["sample_rows"][0]["name"] == "Alice"


def test_dataset_tables_fls_emits_audit_event_when_applied(monkeypatch):  # noqa: ANN001
    from app.api.v1.dataset_tables import get_dataset_table
    from app.services.dataset_service import DatasetService

    dataset_id = uuid.uuid4()
    doc_id = uuid.uuid4()
    table_id = f"doc:{doc_id}:sheet:0"

    class _Dataset:
        def __init__(self) -> None:
            self.id = dataset_id
            self.tenant_id = uuid.uuid4()
            self.name = "Demo"
            self.dataset_metadata = {
                "fls_policy": {
                    "version": "1",
                    "rules": [
                        {
                            "id": "r1",
                            "name": "Mask SSN",
                            "enabled": True,
                            "sources": ["table_store"],
                            "column_name_regex": "^ssn$",
                            "allow_roles": ["owner"],
                            "allow_account_ids": [],
                        }
                    ],
                }
            }

    ds = _Dataset()

    class _Doc:
        def __init__(self) -> None:
            self.id = doc_id
            self.tenant_id = ds.tenant_id
            self.dataset_id = dataset_id
            self.filename = "demo.xlsx"
            self.file_type = "xlsx"
            self.status = "completed"
            self.updated_at = datetime.now(UTC)
            self.doc_metadata = {
                "table_store": {
                    "version": "1",
                    "tables": [
                        {
                            "table_id": table_id,
                            "sheet_index": 0,
                            "sheet_name": "Sheet1",
                            "row_count": 1,
                            "col_count": 2,
                            "truncated": False,
                            "columns": [{"name": "ssn", "dtype": "text"}, {"name": "name", "dtype": "text"}],
                            "sample_rows": [{"ssn": "123-45-6789", "name": "Alice"}],
                        }
                    ],
                }
            }

    doc = _Doc()

    # Dataset access: allow.
    monkeypatch.setattr(DatasetService, "get_dataset", lambda _db, _tenant_id, _did: ds, raising=True)
    monkeypatch.setattr(DatasetService, "assert_dataset_readable", lambda _db, _dataset, _account_id: None, raising=True)

    import app.api.v1.dataset_tables as mod

    # Doc ACL: allow.
    monkeypatch.setattr(mod, "filter_allowed_document_ids", lambda _db, _tenant_id, _account_id, doc_ids: doc_ids, raising=True)

    events: list[str] = []

    def _fake_audit_log_event(_db, **kwargs):  # noqa: ANN001
        events.append(str(kwargs.get("action") or ""))

    monkeypatch.setattr(mod, "audit_log_event", _fake_audit_log_event, raising=True)

    from app.core.config import settings

    monkeypatch.setattr(settings, "TABLE_ROW_REDACTION_ENABLED", False, raising=False)

    class _Member:
        role = "member"

    class _Owner:
        role = "owner"

    # Masked -> audit event.
    monkeypatch.setattr(DatasetService, "ensure_member", lambda _db, _tenant_id, _account_id: _Member(), raising=True)

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db([doc])
    app.dependency_overrides[get_tenant_id] = lambda: ds.tenant_id
    app.dependency_overrides[get_current_account_id] = _override_get_current_account_id

    app.get("/api/v1/datasets/{dataset_id}/tables/{table_id}")(get_dataset_table)
    client = TestClient(app)

    res = client.get(f"/api/v1/datasets/{dataset_id}/tables/{table_id}")
    assert res.status_code == 200
    assert "fls.redaction_applied" in events

    # Allowed -> no event.
    events.clear()
    monkeypatch.setattr(DatasetService, "ensure_member", lambda _db, _tenant_id, _account_id: _Owner(), raising=True)

    res = client.get(f"/api/v1/datasets/{dataset_id}/tables/{table_id}")
    assert res.status_code == 200
    assert "fls.redaction_applied" not in events


def test_dataset_tables_list_includes_pdf_table_store_docs(monkeypatch):  # noqa: ANN001
    """
    Regression: PDF documents can have `doc_metadata.table_store` (parsed tables sidecar) and should be listed.
    """
    from app.api.v1.dataset_tables import list_dataset_tables
    from app.services.dataset_service import DatasetService

    dataset_id = uuid.uuid4()
    doc_id = uuid.uuid4()
    table_id = f"doc:{doc_id}:sheet:0"

    class _Dataset:
        def __init__(self) -> None:
            self.id = dataset_id
            self.tenant_id = uuid.uuid4()
            self.name = "Demo"
            self.dataset_metadata = {}

    ds = _Dataset()

    class _Doc:
        def __init__(self) -> None:
            self.id = doc_id
            self.tenant_id = ds.tenant_id
            self.dataset_id = dataset_id
            self.filename = "demo.pdf"
            self.file_type = "pdf"
            self.status = "completed"
            self.updated_at = datetime.now(UTC)
            self.doc_metadata = {
                "table_store": {
                    "version": "1",
                    "source_ext": ".pdf",
                    "tables": [
                        {
                            "table_id": table_id,
                            "sheet_index": 0,
                            "sheet_name": "Page 1 Table 1",
                            "row_count": 2,
                            "col_count": 2,
                            "truncated": False,
                            "columns": [{"name": "a", "dtype": "int"}, {"name": "b", "dtype": "int"}],
                            "sample_rows": [{"a": 1, "b": 2}],
                        }
                    ],
                }
            }

    doc = _Doc()

    # Dataset access: allow.
    monkeypatch.setattr(DatasetService, "get_dataset", lambda _db, _tenant_id, _did: ds, raising=True)
    monkeypatch.setattr(DatasetService, "assert_dataset_readable", lambda _db, _dataset, _account_id: None, raising=True)

    class _Member:
        role = "member"

    monkeypatch.setattr(DatasetService, "ensure_member", lambda _db, _tenant_id, _account_id: _Member(), raising=True)

    # Doc ACL: allow.
    import app.api.v1.dataset_tables as mod

    monkeypatch.setattr(mod, "get_allowed_document_id_sets", lambda _db, _tenant_id, _account_id, doc_ids, _check_member=False: (set(doc_ids), set()), raising=True)

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db([doc])
    app.dependency_overrides[get_tenant_id] = lambda: ds.tenant_id
    app.dependency_overrides[get_current_account_id] = _override_get_current_account_id

    app.get("/api/v1/datasets/{dataset_id}/tables")(list_dataset_tables)
    client = TestClient(app)

    res = client.get(f"/api/v1/datasets/{dataset_id}/tables")
    assert res.status_code == 200
    payload = res.json()
    assert payload["total"] == 1
    assert payload["items"][0]["table_id"] == table_id


def test_dataset_tables_list_includes_db_row_sidecar_docs(monkeypatch):  # noqa: ANN001
    from app.api.v1.dataset_tables import list_dataset_tables
    from app.services.dataset_service import DatasetService

    dataset_id = uuid.uuid4()
    doc_id = uuid.uuid4()
    table_id = f"doc:{doc_id}:sheet:0"

    class _Dataset:
        def __init__(self) -> None:
            self.id = dataset_id
            self.tenant_id = uuid.uuid4()
            self.name = "Demo"
            self.dataset_metadata = {}

    ds = _Dataset()

    class _Doc:
        def __init__(self) -> None:
            self.id = doc_id
            self.tenant_id = ds.tenant_id
            self.dataset_id = dataset_id
            self.filename = "db_rows_demo.sqlite"
            self.file_type = "dbrows"
            self.status = "completed"
            self.updated_at = datetime.now(UTC)
            self.doc_metadata = {
                "table_store": {
                    "version": "1",
                    "source_ext": ".dbrows",
                    "tables": [
                        {
                            "table_id": table_id,
                            "sheet_index": 0,
                            "sheet_name": "demo.users",
                            "row_count": 2,
                            "col_count": 3,
                            "truncated": False,
                            "columns": [
                                {"name": "id", "dtype": "int"},
                                {"name": "name", "dtype": "text"},
                                {"name": "__row_pk_hash", "dtype": "text"},
                            ],
                            "sample_rows": [{"id": 1, "name": "alice", "__row_pk_hash": "pkhash-1"}],
                            "row_source_table": "demo.users",
                            "row_source_sync_token": "tok-users-v1",
                            "row_source_pk_hash_col": "__row_pk_hash",
                        }
                    ],
                }
            }

    doc = _Doc()

    monkeypatch.setattr(DatasetService, "get_dataset", lambda _db, _tenant_id, _did: ds, raising=True)
    monkeypatch.setattr(DatasetService, "assert_dataset_readable", lambda _db, _dataset, _account_id: None, raising=True)

    class _Member:
        role = "member"

    monkeypatch.setattr(DatasetService, "ensure_member", lambda _db, _tenant_id, _account_id: _Member(), raising=True)

    import app.api.v1.dataset_tables as mod

    monkeypatch.setattr(mod, "get_allowed_document_id_sets", lambda _db, _tenant_id, _account_id, doc_ids, _check_member=False: (set(doc_ids), set()), raising=True)

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db([doc])
    app.dependency_overrides[get_tenant_id] = lambda: ds.tenant_id
    app.dependency_overrides[get_current_account_id] = _override_get_current_account_id

    app.get("/api/v1/datasets/{dataset_id}/tables")(list_dataset_tables)
    client = TestClient(app)

    res = client.get(f"/api/v1/datasets/{dataset_id}/tables")
    assert res.status_code == 200
    payload = res.json()
    assert payload["total"] == 1
    item = payload["items"][0]
    assert item["table_id"] == table_id
    assert item["row_source_table"] == "demo.users"
    assert item["row_source_sync_token"] == "tok-users-v1"
    assert item["row_source_pk_hash_col"] == "__row_pk_hash"

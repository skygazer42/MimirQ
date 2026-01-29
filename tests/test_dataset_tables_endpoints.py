from __future__ import annotations

import uuid
from datetime import datetime, timezone

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
            self.filename = "demo.xlsx"
            self.file_type = "xlsx"
            self.status = "completed"
            self.updated_at = datetime.now(timezone.utc)
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
    monkeypatch.setattr(DatasetService, "get_dataset", lambda db, tenant_id, did: ds, raising=True)
    monkeypatch.setattr(DatasetService, "assert_dataset_readable", lambda db, dataset, account_id: None, raising=True)

    # Doc ACL: allow.
    import app.api.v1.dataset_tables as mod

    monkeypatch.setattr(mod, "filter_allowed_document_ids", lambda db, tenant_id, account_id, doc_ids: doc_ids, raising=True)
    monkeypatch.setattr(mod, "get_allowed_document_id_sets", lambda db, tenant_id, account_id, doc_ids, check_member=False: (set(doc_ids), set()), raising=True)

    # Query executor: stub.
    monkeypatch.setattr(
        mod,
        "run_table_query",
        lambda **kwargs: {"sql": kwargs.get("sql") or "", "columns": ["a", "b"], "rows": [[1, 2]], "truncated": False},
        raising=True,
    )

    # TAG: stub LLM helpers (avoid real network).
    monkeypatch.setattr(mod, "tag_enabled", lambda: True, raising=True)
    monkeypatch.setattr(mod, "generate_sql_for_table", lambda **kwargs: 'SELECT * FROM "sheet_0" LIMIT 10', raising=True)
    monkeypatch.setattr(mod, "generate_answer_from_result", lambda **kwargs: "answer", raising=True)

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
    assert res.json()["answer"] == "answer"

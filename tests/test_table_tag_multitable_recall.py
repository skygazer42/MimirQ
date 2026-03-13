from __future__ import annotations

import json
import uuid

from app.core.config import settings


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

    def all(self):  # noqa: D401
        return list(self._items)


class _FakeDB:
    def __init__(self, docs):  # noqa: ANN001
        self._docs = list(docs or [])

    def query(self, _model):  # noqa: ANN001
        return _FakeQuery(self._docs)


def test_multitable_tag_recall_is_join_deterministic(monkeypatch):  # noqa: ANN001
    from app.services.chat_tag_service import build_chat_tag_context_docs

    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    doc_id = uuid.uuid4()
    table_orders = f"doc:{doc_id}:sheet:0"
    table_users = f"doc:{doc_id}:sheet:1"

    class _Doc:
        def __init__(self) -> None:
            self.id = doc_id
            self.tenant_id = tenant_id
            self.dataset_id = dataset_id
            self.filename = "sales.xlsx"
            self.file_type = "xlsx"
            self.status = "completed"
            self.doc_metadata = {
                "table_store": {
                    "version": "1",
                    "tables": [
                        {
                            "table_id": table_orders,
                            "sheet_index": 0,
                            "sheet_name": "orders",
                            "row_count": 100,
                            "col_count": 2,
                            "truncated": False,
                            "columns": [{"name": "user_id", "dtype": "int"}, {"name": "amount", "dtype": "float"}],
                            "sample_rows": [{"user_id": 1, "amount": 100.0}],
                        },
                        {
                            "table_id": table_users,
                            "sheet_index": 1,
                            "sheet_name": "users",
                            "row_count": 100,
                            "col_count": 2,
                            "truncated": False,
                            "columns": [{"name": "id", "dtype": "int"}, {"name": "region", "dtype": "text"}],
                            "sample_rows": [{"id": 1, "region": "APAC"}],
                        },
                    ],
                }
            }

    monkeypatch.setattr(settings, "CHAT_TAG_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "TABLE_NL2SQL_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "TABLE_LLM_ALLOW_RESULT_EGRESS", True, raising=False)
    monkeypatch.setattr(settings, "LLM_API_KEY", "", raising=False)
    monkeypatch.setattr(settings, "TABLE_NL2SQL_DETERMINISTIC_ONLY", True, raising=False)
    monkeypatch.setattr(settings, "CHAT_TAG_MAX_TABLES", 2, raising=False)

    import app.services.chat_tag_service as mod

    monkeypatch.setattr(
        mod,
        "run_table_query",
        lambda **kwargs: {
            "sql": kwargs.get("sql"),
            "columns": ["region", "total"],
            "rows": [["APAC", 100.0]],
            "truncated": False,
        },
        raising=True,
    )

    docs_a, meta_a = build_chat_tag_context_docs(
        _FakeDB([_Doc()]),
        tenant_id=tenant_id,
        document_ids=[doc_id],
        question="按 region 统计订单金额前10",
    )
    docs_b, meta_b = build_chat_tag_context_docs(
        _FakeDB([_Doc()]),
        tenant_id=tenant_id,
        document_ids=[doc_id],
        question="按 region 统计订单金额前10",
    )

    assert meta_a.get("used") is True and meta_b.get("used") is True
    assert len(docs_a) == 1 and len(docs_b) == 1

    payload_a = json.loads(docs_a[0].page_content)
    payload_b = json.loads(docs_b[0].page_content)

    assert str(payload_a.get("sql") or "") == str(payload_b.get("sql") or "")
    assert "JOIN" in str(payload_a.get("sql") or "").upper()
    assert isinstance(payload_a.get("join_provenance"), list)
    assert payload_a.get("join_provenance") == payload_b.get("join_provenance")
    assert list(payload_a.get("join_table_ids") or []) == [table_orders, table_users]

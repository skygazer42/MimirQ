from __future__ import annotations

import json
import uuid

from app.core.config import settings


class _FakeQuery:
    def __init__(self, items):  # noqa: ANN001
        self._items = list(items or [])

    def filter(self, *args, **kwargs):  # noqa: ANN001,D401
        return self

    def all(self):  # noqa: D401
        return list(self._items)


class _FakeDB:
    def __init__(self, docs):  # noqa: ANN001
        self._docs = list(docs or [])

    def query(self, _model):  # noqa: ANN001
        return _FakeQuery(self._docs)


def test_chat_tag_disabled_returns_empty(monkeypatch):  # noqa: ANN001
    from app.services.chat_tag_service import build_chat_tag_context_docs

    monkeypatch.setattr(settings, "CHAT_TAG_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "TABLE_NL2SQL_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "TABLE_LLM_ALLOW_RESULT_EGRESS", True, raising=False)
    monkeypatch.setattr(settings, "LLM_API_KEY", "test", raising=False)

    docs, meta = build_chat_tag_context_docs(
        _FakeDB([]), tenant_id=uuid.uuid4(), document_ids=[uuid.uuid4()], question="统计一下总数"
    )
    assert docs == []
    assert meta["enabled"] is False
    assert "CHAT_TAG_ENABLED=false" in str(meta.get("reason"))


def test_chat_tag_builds_context_doc(monkeypatch):  # noqa: ANN001
    from app.services.chat_tag_service import build_chat_tag_context_docs

    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    doc_id = uuid.uuid4()
    table_id = f"doc:{doc_id}:sheet:0"

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
                            "table_id": table_id,
                            "sheet_index": 0,
                            "sheet_name": "Sales",
                            "row_count": 10,
                            "col_count": 3,
                            "truncated": False,
                            "columns": [{"name": "amount", "dtype": "int"}, {"name": "region", "dtype": "text"}],
                            "sample_rows": [],
                        }
                    ],
                }
            }

    # Enable feature flags.
    monkeypatch.setattr(settings, "CHAT_TAG_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "TABLE_NL2SQL_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "TABLE_LLM_ALLOW_RESULT_EGRESS", True, raising=False)
    monkeypatch.setattr(settings, "LLM_API_KEY", "test", raising=False)

    # Avoid real LLM + sqlite access.
    import app.services.chat_tag_service as mod

    monkeypatch.setattr(mod, "generate_sql_for_table", lambda **kwargs: 'SELECT "amount" FROM "sheet_0" LIMIT 5', raising=True)
    monkeypatch.setattr(
        mod,
        "run_table_query",
        lambda **kwargs: {"sql": kwargs.get("sql"), "columns": ["amount"], "rows": [[1], [2]], "truncated": False},
        raising=True,
    )

    docs, meta = build_chat_tag_context_docs(
        _FakeDB([_Doc()]),
        tenant_id=tenant_id,
        document_ids=[doc_id],
        question="统计 amount 的前 5 条",
    )
    assert meta["enabled"] is True
    assert meta["used"] is True
    assert len(docs) == 1
    d0 = docs[0]
    assert d0.metadata.get("retrieval_role") == "tag"
    assert d0.metadata.get("document_id") == doc_id
    assert d0.metadata.get("table_id") == table_id
    payload = json.loads(d0.page_content)
    assert payload["kind"] == "tag_table_store"
    assert payload["table_id"] == table_id


def test_chat_tag_too_many_doc_ids_is_rejected(monkeypatch):  # noqa: ANN001
    from app.services.chat_tag_service import build_chat_tag_context_docs

    monkeypatch.setattr(settings, "CHAT_TAG_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "TABLE_NL2SQL_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "TABLE_LLM_ALLOW_RESULT_EGRESS", True, raising=False)
    monkeypatch.setattr(settings, "LLM_API_KEY", "test", raising=False)
    monkeypatch.setattr(settings, "CHAT_TAG_MAX_DOC_IDS", 3, raising=False)

    doc_ids = [uuid.uuid4() for _ in range(4)]
    docs, meta = build_chat_tag_context_docs(_FakeDB([]), tenant_id=uuid.uuid4(), document_ids=doc_ids, question="count?")
    assert docs == []
    assert "too_many_document_ids" in str(meta.get("reason"))

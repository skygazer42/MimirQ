from __future__ import annotations

import json
import uuid

from langchain_core.documents import Document

import app.services.chat_tag_service as chat_tag_service_module
from app.core.config import settings
from app.rag.core.citations import build_citations_from_docs
from app.services.chat_tag_service import build_chat_tag_context_docs


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


def test_db_row_tag_payload_is_deterministic(monkeypatch):  # noqa: ANN001
    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    doc_id = uuid.uuid4()
    table_id = f"doc:{doc_id}:sheet:0"

    class _Doc:
        def __init__(self) -> None:
            self.id = doc_id
            self.tenant_id = tenant_id
            self.dataset_id = dataset_id
            self.filename = "db_rows_demo.sqlite"
            self.file_type = "dbrows"
            self.status = "completed"
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

    monkeypatch.setattr(settings, "CHAT_TAG_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "TABLE_NL2SQL_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "TABLE_LLM_ALLOW_RESULT_EGRESS", True, raising=False)
    monkeypatch.setattr(settings, "LLM_API_KEY", "test", raising=False)

    monkeypatch.setattr(
        chat_tag_service_module,
        "generate_sql_for_table",
        lambda **kwargs: 'SELECT * FROM "sheet_0" LIMIT 10',
        raising=True,
    )
    monkeypatch.setattr(
        chat_tag_service_module,
        "run_table_query",
        lambda **kwargs: {
            "sql": kwargs.get("sql"),
            "columns": ["id", "name", "__row_pk_hash"],
            "rows": [[1, "alice", "pkhash-1"], [2, "bob", "pkhash-2"]],
            "truncated": False,
        },
        raising=True,
    )

    docs1, meta1 = build_chat_tag_context_docs(
        _FakeDB([_Doc()]),
        tenant_id=tenant_id,
        document_ids=[doc_id],
        question="users 表里有谁",
    )
    docs2, meta2 = build_chat_tag_context_docs(
        _FakeDB([_Doc()]),
        tenant_id=tenant_id,
        document_ids=[doc_id],
        question="users 表里有谁",
    )

    assert meta1["used"] is True
    assert meta2["used"] is True
    assert len(docs1) == 1
    assert len(docs2) == 1
    assert docs1[0].id == docs2[0].id

    payload1 = json.loads(docs1[0].page_content)
    payload2 = json.loads(docs2[0].page_content)
    assert payload1.get("row_source") == payload2.get("row_source")
    assert payload1.get("row_source") == {
        "table": "demo.users",
        "sync_token": "tok-users-v1",
        "pk_hashes": ["pkhash-1", "pkhash-2"],
    }


def test_db_row_citation_traceability_fields() -> None:
    doc_id = uuid.uuid4()
    table_id = f"doc:{doc_id}:sheet:0"

    payload = {
        "kind": "tag_table_store",
        "document": "db_rows_demo.sqlite",
        "table_id": table_id,
        "sheet_index": 0,
        "sheet_name": "demo.users",
        "sql": 'SELECT * FROM "sheet_0" LIMIT 10',
        "columns": ["id", "name", "__row_pk_hash"],
        "rows": [[1, "alice", "pkhash-1"]],
        "truncated": False,
        "row_source": {
            "table": "demo.users",
            "sync_token": "tok-users-v1",
            "pk_hashes": ["pkhash-1"],
        },
    }
    docs = [
        Document(
            page_content=json.dumps(payload, ensure_ascii=False),
            id="tag-non-uuid-id",
            metadata={
                "retrieval_role": "tag",
                "chunk_role": "tag_sql_result",
                "document_id": str(doc_id),
                "source": "db_rows_demo.sqlite",
                "table_id": table_id,
                "sheet_index": 0,
                "sheet_name": "demo.users",
                "row_source_table": "demo.users",
                "row_source_sync_token": "tok-users-v1",
                "row_source_pk_hashes": ["pkhash-1"],
                "score": 1.0,
                "retrieval_score": 1.0,
            },
        )
    ]

    citations = build_citations_from_docs(
        docs,
        retrieval_elapsed_sec=0.1,
        retrieval_mode="hybrid",
        query="users 表里有谁",
    )
    assert len(citations) == 1
    c0 = citations[0]
    assert str(c0.get("table_id") or "") == table_id
    assert str(c0.get("row_source_table") or "") == "demo.users"
    assert str(c0.get("row_source_sync_token") or "") == "tok-users-v1"
    assert list(c0.get("row_source_pk_hashes") or []) == ["pkhash-1"]

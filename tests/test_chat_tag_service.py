from __future__ import annotations

import json
import uuid

from app.core.config import settings


class _FakeQuery:
    def __init__(self, items):  # noqa: ANN001
        self._items = list(items or [])

    def filter(self, *args, **kwargs):  # noqa: ANN001,D401
        # Minimal SQLAlchemy filter emulation for unit tests (supports == and IN).
        # This keeps tests meaningful when service code adds/changes filter clauses.
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
    schema_link = payload.get("schema_link") or {}
    assert isinstance(schema_link, dict)
    assert "score" in schema_link
    assert str(schema_link.get("strategy") or "")
    assert d0.metadata.get("schema_link_score") is not None
    assert str(d0.metadata.get("schema_link_strategy") or "")


def test_chat_tag_includes_docx_tables(monkeypatch):  # noqa: ANN001
    """
    Regression: docx documents with `doc_metadata.table_store` should be eligible for TAG.
    """
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
            self.filename = "report.docx"
            self.file_type = "docx"
            self.status = "completed"
            self.doc_metadata = {
                "table_store": {
                    "version": "1",
                    "source_ext": ".docx",
                    "tables": [
                        {
                            "table_id": table_id,
                            "sheet_index": 0,
                            "sheet_name": "Table 1: Sales",
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
    assert docs[0].metadata.get("table_id") == table_id


def test_chat_tag_includes_pdf_tables(monkeypatch):  # noqa: ANN001
    """
    Regression: PDF documents can also have `doc_metadata.table_store` (parsed tables sidecar),
    and should be eligible for TAG.
    """
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
            self.filename = "report.pdf"
            self.file_type = "pdf"
            self.status = "completed"
            self.doc_metadata = {
                "table_store": {
                    "version": "1",
                    "source_ext": ".pdf",
                    "tables": [
                        {
                            "table_id": table_id,
                            "sheet_index": 0,
                            "sheet_name": "Page 1 Table 1",
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
    assert docs[0].metadata.get("table_id") == table_id


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


def test_chat_tag_intent_with_no_match_skips_when_ambiguous(monkeypatch):  # noqa: ANN001
    """
    Selection hardening: when intent is "table-like" but we cannot match any table asset,
    do not run TAG on a random table across multiple document_ids.
    """
    from app.services.chat_tag_service import build_chat_tag_context_docs

    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()

    doc1_id = uuid.uuid4()
    doc2_id = uuid.uuid4()

    class _Doc:
        def __init__(self, *, doc_id: uuid.UUID, filename: str) -> None:
            self.id = doc_id
            self.tenant_id = tenant_id
            self.dataset_id = dataset_id
            self.filename = filename
            self.file_type = "xlsx"
            self.status = "completed"
            self.doc_metadata = {
                "table_store": {
                    "version": "1",
                    "tables": [
                        {
                            "table_id": f"doc:{doc_id}:sheet:0",
                            "sheet_index": 0,
                            "sheet_name": "Sheet1",
                            "row_count": 10,
                            "col_count": 2,
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
    monkeypatch.setattr(settings, "CHAT_TAG_MIN_MATCH_SCORE", 1, raising=False)

    # Ensure we do NOT call LLM/sql runner on ambiguous no-match queries.
    import app.services.chat_tag_service as mod

    monkeypatch.setattr(mod, "generate_sql_for_table", lambda **kwargs: (_ for _ in ()).throw(AssertionError("LLM called")), raising=True)
    monkeypatch.setattr(mod, "run_table_query", lambda **kwargs: (_ for _ in ()).throw(AssertionError("SQL called")), raising=True)

    docs, meta = build_chat_tag_context_docs(
        _FakeDB([_Doc(doc_id=doc1_id, filename="a.xlsx"), _Doc(doc_id=doc2_id, filename="b.xlsx")]),
        tenant_id=tenant_id,
        document_ids=[doc1_id, doc2_id],
        question="统计一下总数",
    )
    assert docs == []
    assert meta.get("used") is False
    assert "ambiguous" in str(meta.get("reason") or "")


def test_chat_tag_intent_with_no_match_falls_back_for_single_document(monkeypatch):  # noqa: ANN001
    """
    Selection fallback: when the user scope is a single document_id, allow TAG for intent queries
    even when we can't match terms to columns/sheet names (common for "这张表有多少行" style questions).
    """
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
                            "sheet_name": "Sheet1",
                            "row_count": 10,
                            "col_count": 2,
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
    monkeypatch.setattr(settings, "CHAT_TAG_MIN_MATCH_SCORE", 1, raising=False)

    # Avoid real LLM + sqlite access.
    import app.services.chat_tag_service as mod

    monkeypatch.setattr(mod, "generate_sql_for_table", lambda **kwargs: 'SELECT COUNT(*) AS n FROM "sheet_0" LIMIT 1', raising=True)
    monkeypatch.setattr(
        mod,
        "run_table_query",
        lambda **kwargs: {"sql": kwargs.get("sql"), "columns": ["n"], "rows": [[10]], "truncated": False},
        raising=True,
    )

    docs, meta = build_chat_tag_context_docs(
        _FakeDB([_Doc()]),
        tenant_id=tenant_id,
        document_ids=[doc_id],
        question="这张表有多少行？",
    )
    assert meta["enabled"] is True
    assert meta["used"] is True
    assert meta.get("selection_fallback") == "single_document"
    assert len(docs) == 1
    assert docs[0].metadata.get("table_id") == table_id


def test_chat_tag_can_match_sample_rows(monkeypatch):  # noqa: ANN001
    """
    Selection improvement: allow picking a table asset based on values seen in metadata sample_rows,
    not just filename/sheet/column names.
    """
    from app.services.chat_tag_service import build_chat_tag_context_docs

    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    doc_id = uuid.uuid4()

    table_a = f"doc:{doc_id}:sheet:0"
    table_b = f"doc:{doc_id}:sheet:1"

    class _Doc:
        def __init__(self) -> None:
            self.id = doc_id
            self.tenant_id = tenant_id
            self.dataset_id = dataset_id
            self.filename = "mixed.xlsx"
            self.file_type = "xlsx"
            self.status = "completed"
            self.doc_metadata = {
                "table_store": {
                    "version": "1",
                    "tables": [
                        {
                            "table_id": table_a,
                            "sheet_index": 0,
                            "sheet_name": "Sheet A",
                            "row_count": 10,
                            "col_count": 2,
                            "truncated": False,
                            "columns": [{"name": "id", "dtype": "int"}, {"name": "value", "dtype": "text"}],
                            "sample_rows": [{"id": 1, "value": "foo"}],
                        },
                        {
                            "table_id": table_b,
                            "sheet_index": 1,
                            "sheet_name": "Sheet B",
                            "row_count": 10,
                            "col_count": 2,
                            "truncated": False,
                            "columns": [{"name": "id", "dtype": "int"}, {"name": "value", "dtype": "text"}],
                            "sample_rows": [{"id": 1, "value": "acme"}],
                        },
                    ],
                }
            }

    monkeypatch.setattr(settings, "CHAT_TAG_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "TABLE_NL2SQL_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "TABLE_LLM_ALLOW_RESULT_EGRESS", True, raising=False)
    monkeypatch.setattr(settings, "LLM_API_KEY", "test", raising=False)
    monkeypatch.setattr(settings, "CHAT_TAG_MIN_MATCH_SCORE", 1, raising=False)
    monkeypatch.setattr(settings, "CHAT_TAG_MAX_TABLES", 1, raising=False)

    import app.services.chat_tag_service as mod

    chosen: dict[str, str] = {}

    monkeypatch.setattr(mod, "generate_sql_for_table", lambda **kwargs: 'SELECT "value" FROM "sheet_0" LIMIT 5', raising=True)

    def _fake_run_table_query(**kwargs):  # noqa: ANN001
        chosen["table_id"] = str(kwargs.get("table_id") or "")
        return {"sql": kwargs.get("sql"), "columns": ["value"], "rows": [["acme"]], "truncated": False}

    monkeypatch.setattr(mod, "run_table_query", _fake_run_table_query, raising=True)

    docs, meta = build_chat_tag_context_docs(
        _FakeDB([_Doc()]),
        tenant_id=tenant_id,
        document_ids=[doc_id],
        question="acme",
    )
    assert meta["enabled"] is True
    assert meta["used"] is True
    assert len(docs) == 1
    assert chosen.get("table_id") == table_b


def test_chat_tag_uses_deterministic_sql_when_llm_key_missing(monkeypatch):  # noqa: ANN001
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
                            "col_count": 2,
                            "truncated": False,
                            "columns": [{"name": "amount", "dtype": "int"}, {"name": "region", "dtype": "text"}],
                            "sample_rows": [],
                        }
                    ],
                }
            }

    monkeypatch.setattr(settings, "CHAT_TAG_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "TABLE_NL2SQL_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "TABLE_LLM_ALLOW_RESULT_EGRESS", True, raising=False)
    monkeypatch.setattr(settings, "LLM_API_KEY", "", raising=False)
    monkeypatch.setattr(settings, "TABLE_NL2SQL_DETERMINISTIC_FALLBACK_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "TABLE_NL2SQL_DETERMINISTIC_ONLY", False, raising=False)

    import app.services.chat_tag_service as mod

    monkeypatch.setattr(
        mod,
        "run_table_query",
        lambda **kwargs: {"sql": kwargs.get("sql"), "columns": ["count"], "rows": [[10]], "truncated": False},
        raising=True,
    )

    docs, meta = build_chat_tag_context_docs(
        _FakeDB([_Doc()]),
        tenant_id=tenant_id,
        document_ids=[doc_id],
        question="总数有多少",
    )
    assert meta["enabled"] is True
    assert meta["used"] is True
    assert len(docs) == 1

    payload = json.loads(docs[0].page_content)
    assert payload.get("table_id") == table_id
    assert payload.get("sql_generation_mode") == "deterministic"
    schema_link = payload.get("schema_link") or {}
    assert isinstance(schema_link, dict)
    assert float(schema_link.get("score") or 0.0) > 0.0
    assert str(schema_link.get("strategy") or "")
    assert docs[0].metadata.get("schema_link_score") is not None
    assert str(docs[0].metadata.get("schema_link_strategy") or "")
    assert "count" in str(payload.get("sql") or "").lower()


def test_chat_tag_dbrows_sql_first_forces_deterministic_even_with_llm(monkeypatch):  # noqa: ANN001
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
            self.filename = "inventory.sqlite"
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
                            "sheet_name": "demo.inventory",
                            "row_count": 10,
                            "col_count": 2,
                            "truncated": False,
                            "columns": [{"name": "sku", "dtype": "text"}, {"name": "qty", "dtype": "int"}],
                            "sample_rows": [],
                        }
                    ],
                }
            }

    monkeypatch.setattr(settings, "CHAT_TAG_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "TABLE_NL2SQL_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "TABLE_LLM_ALLOW_RESULT_EGRESS", True, raising=False)
    monkeypatch.setattr(settings, "LLM_API_KEY", "test-key", raising=False)
    monkeypatch.setattr(settings, "TABLE_NL2SQL_DETERMINISTIC_ONLY", False, raising=False)
    monkeypatch.setattr(settings, "TABLE_NL2SQL_DETERMINISTIC_FALLBACK_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "CHAT_TAG_DBROWS_SQL_FIRST_ENABLED", True, raising=False)

    import app.services.chat_tag_service as mod

    monkeypatch.setattr(
        mod,
        "generate_sql_for_table",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("LLM SQL path should not be used for dbrows sql-first")),
        raising=True,
    )
    monkeypatch.setattr(
        mod,
        "generate_sql_for_table_with_metadata",
        lambda **_kwargs: (
            'SELECT "sku","qty" FROM "sheet_0" LIMIT 10',
            "deterministic",
            {"schema_link": {"score": 0.8, "strategy": "column_overlap"}, "planner": {"strategy": "deterministic_heuristic"}},
        ),
        raising=True,
    )
    monkeypatch.setattr(
        mod,
        "run_table_query",
        lambda **kwargs: {"sql": kwargs.get("sql"), "columns": ["sku", "qty"], "rows": [["A1", 2]], "truncated": False},
        raising=True,
    )

    docs, meta = build_chat_tag_context_docs(
        _FakeDB([_Doc()]),
        tenant_id=tenant_id,
        document_ids=[doc_id],
        question="inventory 表里数量",
    )
    assert meta["enabled"] is True
    assert meta["used"] is True
    assert len(docs) == 1

    payload = json.loads(docs[0].page_content)
    assert payload.get("sql_generation_mode") == "deterministic"
    assert str(payload.get("table_id") or "") == table_id


def test_chat_tag_must_recall_source_keys_filter_candidates(monkeypatch):  # noqa: ANN001
    from app.services.chat_tag_service import build_chat_tag_context_docs

    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    doc_id = uuid.uuid4()
    table_sales = f"doc:{doc_id}:sheet:0"
    table_inventory = f"doc:{doc_id}:sheet:1"

    class _Doc:
        def __init__(self) -> None:
            self.id = doc_id
            self.tenant_id = tenant_id
            self.dataset_id = dataset_id
            self.filename = "mixed.xlsx"
            self.file_type = "xlsx"
            self.status = "completed"
            self.doc_metadata = {
                "table_store": {
                    "version": "1",
                    "tables": [
                        {
                            "table_id": table_sales,
                            "sheet_index": 0,
                            "sheet_name": "sales",
                            "row_count": 10,
                            "col_count": 2,
                            "truncated": False,
                            "columns": [{"name": "amount", "dtype": "int"}],
                            "sample_rows": [],
                        },
                        {
                            "table_id": table_inventory,
                            "sheet_index": 1,
                            "sheet_name": "inventory",
                            "row_count": 10,
                            "col_count": 2,
                            "truncated": False,
                            "columns": [{"name": "qty", "dtype": "int"}],
                            "sample_rows": [],
                        },
                    ],
                }
            }

    monkeypatch.setattr(settings, "CHAT_TAG_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "TABLE_NL2SQL_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "TABLE_LLM_ALLOW_RESULT_EGRESS", True, raising=False)
    monkeypatch.setattr(settings, "CHAT_TAG_MUST_RECALL_SOURCE_KEY_MATCH", True, raising=False)
    monkeypatch.setattr(settings, "LLM_API_KEY", "test", raising=False)
    monkeypatch.setattr(settings, "CHAT_TAG_MAX_TABLES", 1, raising=False)

    import app.services.chat_tag_service as mod

    chosen: dict[str, str] = {}
    monkeypatch.setattr(mod, "generate_sql_for_table", lambda **_kwargs: 'SELECT COUNT(*) AS n FROM "sheet_0" LIMIT 1', raising=True)

    def _fake_run_table_query(**kwargs):  # noqa: ANN001
        chosen["table_id"] = str(kwargs.get("table_id") or "")
        return {"sql": kwargs.get("sql"), "columns": ["n"], "rows": [[10]], "truncated": False}

    monkeypatch.setattr(mod, "run_table_query", _fake_run_table_query, raising=True)

    docs, meta = build_chat_tag_context_docs(
        _FakeDB([_Doc()]),
        tenant_id=tenant_id,
        document_ids=[doc_id],
        question="统计 inventory",
        must_recall_expected_source_keys=["inventory"],
    )
    assert meta.get("must_recall_source_key_match_applied") is True
    assert meta.get("must_recall_source_key_match_candidates_before") == 2
    assert meta.get("must_recall_source_key_match_candidates_after") == 1
    assert len(docs) == 1
    assert chosen.get("table_id") == table_inventory


def test_chat_tag_must_recall_source_keys_miss_returns_empty(monkeypatch):  # noqa: ANN001
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
                            "sheet_name": "sales",
                            "row_count": 10,
                            "col_count": 2,
                            "truncated": False,
                            "columns": [{"name": "amount", "dtype": "int"}],
                            "sample_rows": [],
                        }
                    ],
                }
            }

    monkeypatch.setattr(settings, "CHAT_TAG_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "TABLE_NL2SQL_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "TABLE_LLM_ALLOW_RESULT_EGRESS", True, raising=False)
    monkeypatch.setattr(settings, "CHAT_TAG_MUST_RECALL_SOURCE_KEY_MATCH", True, raising=False)
    monkeypatch.setattr(settings, "LLM_API_KEY", "test", raising=False)

    docs, meta = build_chat_tag_context_docs(
        _FakeDB([_Doc()]),
        tenant_id=tenant_id,
        document_ids=[doc_id],
        question="统计 sales",
        must_recall_expected_source_keys=["inventory"],
    )
    assert docs == []
    assert str(meta.get("reason") or "") == "must_recall_source_key_miss"
    assert int(meta.get("must_recall_source_key_match_candidates_after") or 0) == 0


def test_chat_tag_selection_tie_break_is_deterministic(monkeypatch):  # noqa: ANN001
    from app.services.chat_tag_service import build_chat_tag_context_docs

    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    doc_id = uuid.uuid4()
    table_a = f"doc:{doc_id}:sheet:1"
    table_b = f"doc:{doc_id}:sheet:2"

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
                            "table_id": table_b,
                            "sheet_index": 2,
                            "sheet_name": "B",
                            "row_count": 10,
                            "col_count": 2,
                            "truncated": False,
                            "columns": [{"name": "amount", "dtype": "int"}],
                            "sample_rows": [],
                        },
                        {
                            "table_id": table_a,
                            "sheet_index": 1,
                            "sheet_name": "A",
                            "row_count": 10,
                            "col_count": 2,
                            "truncated": False,
                            "columns": [{"name": "amount", "dtype": "int"}],
                            "sample_rows": [],
                        },
                    ],
                }
            }

    monkeypatch.setattr(settings, "CHAT_TAG_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "TABLE_NL2SQL_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "TABLE_LLM_ALLOW_RESULT_EGRESS", True, raising=False)
    monkeypatch.setattr(settings, "LLM_API_KEY", "test", raising=False)
    monkeypatch.setattr(settings, "CHAT_TAG_MIN_MATCH_SCORE", 1, raising=False)
    monkeypatch.setattr(settings, "CHAT_TAG_MAX_TABLES", 1, raising=False)

    import app.services.chat_tag_service as mod

    chosen: dict[str, str] = {}

    monkeypatch.setattr(mod, "generate_sql_for_table", lambda **kwargs: 'SELECT COUNT(*) AS n FROM "sheet_0" LIMIT 1', raising=True)

    def _fake_run_table_query(**kwargs):  # noqa: ANN001
        chosen["table_id"] = str(kwargs.get("table_id") or "")
        return {"sql": kwargs.get("sql"), "columns": ["n"], "rows": [[10]], "truncated": False}

    monkeypatch.setattr(mod, "run_table_query", _fake_run_table_query, raising=True)

    docs, meta = build_chat_tag_context_docs(
        _FakeDB([_Doc()]),
        tenant_id=tenant_id,
        document_ids=[doc_id],
        question="这张表有多少行？",
    )
    assert meta["enabled"] is True
    assert meta["used"] is True
    assert len(docs) == 1
    # Same score/row_count/filename: final tie-break is table_id lexical order.
    assert chosen.get("table_id") == min(table_a, table_b)


def test_chat_tag_carries_db_row_source_metadata_into_payload(monkeypatch):  # noqa: ANN001
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

    import app.services.chat_tag_service as mod

    monkeypatch.setattr(mod, "generate_sql_for_table", lambda **kwargs: 'SELECT * FROM "sheet_0" LIMIT 10', raising=True)
    monkeypatch.setattr(
        mod,
        "run_table_query",
        lambda **kwargs: {
            "sql": kwargs.get("sql"),
            "columns": ["id", "name", "__row_pk_hash"],
            "rows": [[1, "alice", "pkhash-1"], [2, "bob", "pkhash-2"]],
            "truncated": False,
        },
        raising=True,
    )

    docs, meta = build_chat_tag_context_docs(
        _FakeDB([_Doc()]),
        tenant_id=tenant_id,
        document_ids=[doc_id],
        question="users 表里有谁",
    )
    assert meta["enabled"] is True
    assert meta["used"] is True
    assert len(docs) == 1

    payload = json.loads(docs[0].page_content)
    row_source = payload.get("row_source") or {}
    assert str(row_source.get("table") or "") == "demo.users"
    assert str(row_source.get("sync_token") or "") == "tok-users-v1"
    assert list(row_source.get("pk_hashes") or []) == ["pkhash-1", "pkhash-2"]

    md = docs[0].metadata
    assert str(md.get("row_source_table") or "") == "demo.users"
    assert str(md.get("row_source_sync_token") or "") == "tok-users-v1"


def test_chat_tag_builds_multitable_join_payload(monkeypatch):  # noqa: ANN001
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
                            "row_count": 10,
                            "col_count": 2,
                            "truncated": False,
                            "columns": [{"name": "user_id", "dtype": "int"}, {"name": "amount", "dtype": "float"}],
                            "sample_rows": [{"user_id": 1, "amount": 100.0}],
                        },
                        {
                            "table_id": table_users,
                            "sheet_index": 1,
                            "sheet_name": "users",
                            "row_count": 10,
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
            "planner_execution_mismatch": {"mismatch": False, "reasons": []},
        },
        raising=True,
    )

    docs, meta = build_chat_tag_context_docs(
        _FakeDB([_Doc()]),
        tenant_id=tenant_id,
        document_ids=[doc_id],
        question="按 region 统计订单金额前10",
    )
    assert meta["enabled"] is True
    assert meta["used"] is True
    assert str(meta.get("table_pick_policy") or "") == "complexity_schema_link_multi_table"
    assert len(docs) == 1

    payload = json.loads(docs[0].page_content)
    assert "JOIN" in str(payload.get("sql") or "").upper()
    join_prov = payload.get("join_provenance")
    assert isinstance(join_prov, list)
    assert len(join_prov) == 1
    assert str((join_prov[0] or {}).get("left_table") or "").startswith("sheet_")
    assert str((join_prov[0] or {}).get("right_table") or "").startswith("sheet_")
    assert str(payload.get("sql_fingerprint") or "")
    assert bool((payload.get("planner_execution_mismatch") or {}).get("mismatch")) is False

    md = docs[0].metadata
    assert isinstance(md.get("join_provenance"), list)
    assert list(md.get("join_table_ids") or []) == [table_orders, table_users]
    assert str(md.get("sql_fingerprint") or "")

from __future__ import annotations

import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient
from langchain_core.documents import Document

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.core.database import get_db


class _FakeDB:
    """Minimal DB stub for chat endpoint unit tests (no real SQLAlchemy engine)."""

    def __init__(self) -> None:
        self.added: list[object] = []

    def add(self, obj):  # noqa: ANN001
        self.added.append(obj)

    def flush(self) -> None:  # noqa: D401
        return None

    def commit(self) -> None:  # noqa: D401
        return None


def _override_get_db():  # noqa: ANN001
    def _gen():  # noqa: ANN202
        yield _FakeDB()

    return _gen


def test_chat_graph_injects_tag_docs_into_state(monkeypatch):  # noqa: ANN001
    """
    Regression: chat(use_graph=True) should pass TAG docs into LangGraph state (tag_docs/tag_meta).

    We stub:
    - build_chat_tag_context_docs to avoid LLM/DB work
    - rag_workflow.invoke to capture the state passed in
    """
    from app.api.v1.chat import chat as chat_endpoint

    tenant_id = uuid.uuid4()
    doc_id = uuid.uuid4()

    # Avoid real document ACL lookup.
    import app.services.chat_scope as chat_scope_mod

    monkeypatch.setattr(
        chat_scope_mod,
        "filter_allowed_document_ids",
        lambda _db, _tenant_id, _account_id, doc_ids: doc_ids,
        raising=True,
    )

    # Stub TAG builder to inject a deterministic context doc.
    import app.services.chat_tag_service as tag_mod

    injected_doc = Document(
        page_content='{"kind":"tag_table_store","sql":"SELECT 1"}',
        metadata={
            "document_id": doc_id,
            "source": "demo.xlsx",
            "retrieval_role": "tag",
            "chunk_strategy": "tag",
            "chunk_role": "tag_sql_result",
            "retrieval_score": 1.0,
            "score": 1.0,
            "table_id": f"doc:{doc_id}:sheet:0",
        },
        id=f"tag:doc:{doc_id}:sheet:0",
    )

    def _fake_build_chat_tag_context_docs(db, *, tenant_id, document_ids, question):  # noqa: ANN001
        return [injected_doc], {"enabled": True, "used": True, "reason": "ok", "returned": 1}

    monkeypatch.setattr(tag_mod, "build_chat_tag_context_docs", _fake_build_chat_tag_context_docs, raising=True)

    # Capture state passed to LangGraph invoke.
    import app.rag.pipelines.langgraph as lg_mod

    captured: dict[str, object] = {}

    def _fake_invoke(state, config=None, context=None):  # noqa: ANN001
        captured["state"] = state
        return {"citations": [], "answer": "ok", "metrics": {}}

    monkeypatch.setattr(lg_mod.rag_workflow, "invoke", _fake_invoke, raising=False)

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db()
    app.dependency_overrides[get_tenant_id] = lambda: tenant_id
    app.dependency_overrides[get_current_account_id] = lambda: "test-account"

    app.post("/api/v1/chat")(chat_endpoint)

    client = TestClient(app)
    res = client.post(
        "/api/v1/chat",
        json={
            "message": "统计这张表里有多少行？",
            "document_ids": [str(doc_id)],
            "stream": False,
            "rag_config": {"use_graph": True},
        },
    )
    assert res.status_code == 200

    st = captured.get("state")
    assert isinstance(st, dict)
    assert "tag_docs" in st
    assert "tag_meta" in st

    tag_docs = st.get("tag_docs")
    assert isinstance(tag_docs, list)
    assert len(tag_docs) == 1
    assert isinstance(tag_docs[0], Document)
    assert tag_docs[0].metadata.get("retrieval_role") == "tag"
    assert isinstance(st.get("tag_meta"), dict)
    assert st["tag_meta"].get("enabled") is True


def test_chat_graph_passes_hierarchy_recall_fields_into_state(monkeypatch):  # noqa: ANN001
    from app.api.v1.chat import chat as chat_endpoint

    tenant_id = uuid.uuid4()
    doc_id = uuid.uuid4()

    import app.services.chat_scope as chat_scope_mod

    monkeypatch.setattr(
        chat_scope_mod,
        "filter_allowed_document_ids",
        lambda _db, _tenant_id, _account_id, doc_ids: doc_ids,
        raising=True,
    )

    import app.services.chat_tag_service as tag_mod

    monkeypatch.setattr(
        tag_mod,
        "build_chat_tag_context_docs",
        lambda db, *, tenant_id, document_ids, question: ([], {"enabled": False, "used": False, "returned": 0}),
        raising=True,
    )

    import app.rag.pipelines.langgraph as lg_mod

    captured: dict[str, object] = {}

    def _fake_invoke(state, config=None, context=None):  # noqa: ANN001
        captured["state"] = state
        return {"citations": [], "answer": "ok", "metrics": {}}

    monkeypatch.setattr(lg_mod.rag_workflow, "invoke", _fake_invoke, raising=False)

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db()
    app.dependency_overrides[get_tenant_id] = lambda: tenant_id
    app.dependency_overrides[get_current_account_id] = lambda: "test-account"

    app.post("/api/v1/chat")(chat_endpoint)

    client = TestClient(app)
    res = client.post(
        "/api/v1/chat",
        json={
            "message": "Summarize the section layout.",
            "document_ids": [str(doc_id)],
            "stream": False,
            "rag_config": {"use_graph": True, "retrieval_profile": "hierarchy_recall20"},
        },
    )
    assert res.status_code == 200

    st = captured.get("state")
    assert isinstance(st, dict)
    assert st.get("retrieval_profile") == "hierarchy_recall20"
    assert st.get("enable_hierarchy_recall") is True
    assert st.get("hierarchy_family_collapse") is True
    assert st.get("hierarchy_overfetch_factor") == 4

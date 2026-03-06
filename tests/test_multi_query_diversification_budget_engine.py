from __future__ import annotations

import json
import uuid

import pytest
from langchain_core.documents import Document
from langchain_core.language_models.fake_chat_models import FakeListChatModel


class _RoutingRetriever:
    def __init__(self, *, main_docs: list[Document], mq_docs: dict[str, list[Document]]) -> None:
        self._main_docs = list(main_docs)
        self._mq_docs = {str(k): list(v) for k, v in (mq_docs or {}).items()}
        self._last_debug_metrics: dict = {}

    def model_copy(self, **_kwargs):  # noqa: ANN001, ANN002, ANN003
        return self

    def invoke(self, q: str):  # noqa: ANN001
        q = (q or "").strip()
        if q == "BASE":
            return list(self._main_docs)
        return list(self._mq_docs.get(q, []))


def _mk_doc(*, doc_id: str, chunk_index: int) -> Document:
    chunk_id = f"{doc_id}:{chunk_index}"
    return Document(
        page_content=f"{chunk_id} content",
        id=chunk_id,
        metadata={
            "document_id": doc_id,
            "chunk_id": chunk_id,
            "chunk_index": int(chunk_index),
            "source": "t.md",
            "score": 1.0,
        },
    )


@pytest.mark.asyncio
async def test_engine_multi_query_diversify_budget_caps_mq_role(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import settings
    from app.rag.engine import RAGEngine

    # Keep offline/deterministic.
    monkeypatch.setattr(settings, "ENABLE_QUERY_REWRITE", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_HYDE", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_QUERY_DECOMPOSITION", False, raising=False)
    monkeypatch.setattr(settings, "RETRIEVAL_QUERY_PARALLELISM", 1, raising=False)
    monkeypatch.setattr(settings, "KG_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "KG_CHAT_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "RAG_KG_CHUNK_INJECTION_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "RAG_KG_QUERY_EXPANSION_ENABLED", False, raising=False)

    # Avoid dict expansion.
    import app.query.expand as expand_mod

    monkeypatch.setattr(expand_mod, "load_base_dictionary_rules", lambda: [], raising=True)
    monkeypatch.setattr(
        expand_mod,
        "generate_dictionary_expansions",
        lambda **_k: ([], {"enabled": False, "used": False}),
        raising=True,
    )

    # Enable multi-query with many variants + diversification budget.
    monkeypatch.setattr(settings, "ENABLE_MULTI_QUERY", True, raising=False)
    monkeypatch.setattr(settings, "MULTI_QUERY_COUNT", 5, raising=False)
    monkeypatch.setattr(settings, "MULTI_QUERY_TEMPERATURE", 0.0, raising=False)
    monkeypatch.setattr(settings, "MULTI_QUERY_MAX_CHARS", 200, raising=False)
    monkeypatch.setattr(settings, "MULTI_QUERY_DIVERSIFY_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "MULTI_QUERY_DIVERSIFY_BUDGET", 1, raising=False)

    engine = RAGEngine()

    # Fake models to avoid external calls.
    mq_queries = [f"ALT{i}" for i in range(1, 6)]
    fake_fast = FakeListChatModel(responses=[json.dumps(mq_queries)])
    fake_gen = FakeListChatModel(responses=["ok"])
    engine.models["fast"] = fake_fast
    monkeypatch.setattr(engine, "_select_llm", lambda *_a, **_k: (fake_gen, "fake", "test"), raising=True)

    main_docs = [_mk_doc(doc_id="z-main", chunk_index=i) for i in range(0, 4)]
    mq_docs = {q: [_mk_doc(doc_id=f"a-{q.lower()}", chunk_index=0)] for q in mq_queries}
    fake_retriever = _RoutingRetriever(main_docs=main_docs, mq_docs=mq_docs)

    import app.rag.engine as engine_mod

    monkeypatch.setattr(engine_mod, "hybrid_retriever", fake_retriever, raising=True)

    agen = engine.stream_chat(
        question="BASE",
        history=[],
        tenant_id=uuid.uuid4(),
        account_id="u",
        document_ids=[uuid.uuid4()],
        top_k=4,
        score_threshold=0.0,
        retrieval_mode="vector",
        request_id="test",
    )
    try:
        citations = None
        async for ev in agen:
            if ev.get("type") == "citations":
                citations = ev.get("data")
                break
        assert isinstance(citations, list)
        assert len(citations) == 4
        mq_count = 0
        main_count = 0
        for c in citations:
            if not isinstance(c, dict):
                continue
            role = str(c.get("retrieval_role") or "main")
            if role == "mq":
                mq_count += 1
            if role == "main":
                main_count += 1
        assert mq_count <= 1
        assert main_count >= 3
    finally:
        await agen.aclose()

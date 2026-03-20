from __future__ import annotations

import uuid

import pytest
from langchain_core.documents import Document
from langchain_core.language_models.fake_chat_models import FakeListChatModel


class _FakeRetriever:
    def __init__(self, *, docs: list[Document]) -> None:
        self._docs = list(docs)
        self._last_debug_metrics: dict = {}

    def model_copy(self, **_kwargs):  # noqa: ANN001, ANN002, ANN003
        return self

    def invoke(self, _q: str):  # noqa: ANN001
        return list(self._docs)


@pytest.mark.asyncio
async def test_engine_emits_query_rewrite_strategy_meta(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Query rewrite is versioned; the engine should emit a PII-safe (id, hash) in the rewrite event.
    """
    from app.api.schemas.chat import ChatRAGConfig
    from app.core.config import settings
    from app.rag.engine import RAGChatContext, RAGEngine

    # Keep things offline/deterministic.
    monkeypatch.setattr(settings, "ENABLE_QUERY_REWRITE", True, raising=False)
    monkeypatch.setattr(settings, "QUERY_REWRITE_STRATEGY", "kb_followup.v1", raising=False)
    monkeypatch.setattr(settings, "ENABLE_MULTI_QUERY", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_HYDE", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_QUERY_DECOMPOSITION", False, raising=False)
    monkeypatch.setattr(settings, "RETRIEVAL_QUERY_PARALLELISM", 1, raising=False)
    monkeypatch.setattr(settings, "KG_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "KG_CHAT_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "RAG_KG_CHUNK_INJECTION_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "RAG_KG_QUERY_EXPANSION_ENABLED", False, raising=False)

    # Avoid dict expansion interfering with execution.
    import app.query.expand as expand_mod

    monkeypatch.setattr(expand_mod, "load_base_dictionary_rules", lambda: [], raising=True)
    monkeypatch.setattr(
        expand_mod,
        "generate_dictionary_expansions",
        lambda **_k: ([], {"enabled": False, "used": False}),
        raising=True,
    )

    engine = RAGEngine()

    fake_rewrite_llm = FakeListChatModel(responses=["standalone rewritten query"])
    fake_gen_llm = FakeListChatModel(responses=["ok"])

    # Force a fake LLM selection to avoid any external dependencies.
    monkeypatch.setattr(engine, "_select_llm", lambda *_a, **_k: (fake_gen_llm, "fake", "test"), raising=True)
    engine.models["fast"] = fake_rewrite_llm

    # Patch retriever so the generator can proceed if needed.
    doc_id = uuid.uuid4()
    chunk_id = uuid.uuid4()
    fake_retriever = _FakeRetriever(
        docs=[
            Document(
                page_content="hit",
                id=str(chunk_id),
                metadata={
                    "document_id": str(doc_id),
                    "chunk_id": str(chunk_id),
                    "chunk_index": 0,
                    "source": "t.md",
                    "score": 0.9,
                },
            )
        ]
    )
    import app.rag.engine as engine_mod

    monkeypatch.setattr(engine_mod, "hybrid_retriever", fake_retriever, raising=True)

    history = [{"role": "user", "content": "Earlier we talked about Retry-After and 429."}]
    question = "it?"

    agen = engine.stream_chat(
        question=question,
        context=RAGChatContext(
            history=history,
            tenant_id=uuid.uuid4(),
            account_id="u",
            document_ids=[doc_id],
            request_id="test",
        ),
        rag_config=ChatRAGConfig(
            top_k=5,
            score_threshold=0.0,
            retrieval_mode="vector",
        ),
    )
    try:
        rewrite_ev = None
        async for ev in agen:
            if ev.get("type") == "rewrite":
                rewrite_ev = ev
                break
        assert isinstance(rewrite_ev, dict)
        data = rewrite_ev.get("data")
        assert isinstance(data, dict)
        assert data.get("strategy_id") == "kb_followup.v1"
        assert isinstance(data.get("strategy_hash"), str) and len(data.get("strategy_hash") or "") >= 8
    finally:
        await agen.aclose()

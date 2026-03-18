from __future__ import annotations

import uuid

import pytest
from langchain_core.documents import Document
from langchain_core.language_models.fake_chat_models import FakeListChatModel


class _RoutingRetriever:
    def __init__(self, *, main_query: str, step_back_query: str) -> None:
        self._main_query = str(main_query)
        self._step_back_query = str(step_back_query)
        self._last_debug_metrics: dict = {}
        self.invoked: list[str] = []

    def model_copy(self, **_kwargs):  # noqa: ANN001, ANN002, ANN003
        return self

    def invoke(self, q: str):  # noqa: ANN001
        query = str(q or "").strip()
        self.invoked.append(query)
        if query == self._main_query:
            return [
                Document(
                    page_content="main evidence",
                    id="main:0",
                    metadata={
                        "document_id": "main",
                        "chunk_id": "main:0",
                        "source": "main.md",
                        "score": 0.9,
                    },
                )
            ]
        if query == self._step_back_query:
            return [
                Document(
                    page_content="step back evidence",
                    id="sb:0",
                    metadata={
                        "document_id": "sb",
                        "chunk_id": "sb:0",
                        "source": "sb.md",
                        "score": 0.85,
                    },
                )
            ]
        return []


@pytest.mark.asyncio
async def test_engine_step_back_query_expansion_adds_step_back_variant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rag.engine as engine_mod
    from app.core.config import settings
    from app.rag.engine import RAGEngine

    engine_mod.reset_rag_engine()

    # Keep deterministic and focused on step-back behavior.
    monkeypatch.setattr(settings, "ENABLE_QUERY_REWRITE", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_MULTI_QUERY", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_HYDE", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_QUERY_DECOMPOSITION", False, raising=False)
    monkeypatch.setattr(settings, "RAG_KG_QUERY_EXPANSION_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "KG_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "KG_CHAT_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "RAG_KG_CHUNK_INJECTION_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "RETRIEVAL_QUERY_PARALLELISM", 1, raising=False)
    monkeypatch.setattr(settings, "RAG_VISIBLE_EVIDENCE_ONLY_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "RAG_ABSTAIN_ENABLED", False, raising=False)

    monkeypatch.setattr(settings, "ENABLE_STEP_BACK_QUERY", True, raising=False)
    monkeypatch.setattr(settings, "STEP_BACK_TEMPERATURE", 0.0, raising=False)
    monkeypatch.setattr(settings, "STEP_BACK_MAX_CHARS", 200, raising=False)
    monkeypatch.setattr(settings, "STEP_BACK_OUTPUT_MAX_CHARS", 200, raising=False)

    # Avoid dict expansion noise.
    import app.query.expand as expand_mod

    monkeypatch.setattr(expand_mod, "load_base_dictionary_rules", lambda: [], raising=True)
    monkeypatch.setattr(
        expand_mod,
        "generate_dictionary_expansions",
        lambda **_k: ([], {"enabled": False, "used": False}),
        raising=True,
    )

    main_query = "BASE"
    step_back_query = "What general principles explain BASE?"

    engine = RAGEngine()
    step_back_llm = FakeListChatModel(responses=[step_back_query])
    fake_gen = FakeListChatModel(responses=["ok"])
    engine.models["fast"] = step_back_llm
    monkeypatch.setattr(engine, "_select_llm", lambda *_a, **_k: (fake_gen, "fake", "test"), raising=True)

    retriever = _RoutingRetriever(main_query=main_query, step_back_query=step_back_query)
    monkeypatch.setattr(engine_mod, "hybrid_retriever", retriever, raising=True)

    agen = engine.stream_chat(
        question=main_query,
        history=[],
        tenant_id=uuid.uuid4(),
        account_id="u",
        document_ids=[uuid.uuid4()],
        top_k=2,
        score_threshold=0.0,
        retrieval_mode="vector",
        request_id="test-step-back-engine",
    )
    try:
        done_data = None
        citations_data = []
        async for ev in agen:
            if ev.get("type") == "citations":
                citations_data = ev.get("data") or []
            if ev.get("type") == "done":
                done_data = ev.get("data") or {}
                break
        metrics = (done_data or {}).get("metrics") or {}
        assert metrics.get("step_back_enabled") is True
        assert metrics.get("step_back_used") is True
        assert metrics.get("step_back_parse_ok") is True
        assert metrics.get("step_back_parse_method") == "text"
        assert main_query in (retriever.invoked or [])
        assert step_back_query in (retriever.invoked or [])
        assert any((c or {}).get("retrieval_role") == "step_back" for c in (citations_data or []))
    finally:
        await agen.aclose()


def test_langgraph_step_back_query_expansion_adds_step_back_variant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rag.pipelines.langgraph as lg_mod
    import app.rag.retrieval.orchestrator as orch_mod
    from app.core.config import settings
    from app.rag.engine import RAGEngine

    # Keep deterministic and focused on step-back behavior.
    monkeypatch.setattr(settings, "ENABLE_QUERY_REWRITE", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_MULTI_QUERY", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_HYDE", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_QUERY_DECOMPOSITION", False, raising=False)
    monkeypatch.setattr(settings, "RAG_KG_QUERY_EXPANSION_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "KG_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "KG_CHAT_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "RAG_KG_CHUNK_INJECTION_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "RETRIEVAL_QUERY_PARALLELISM", 1, raising=False)

    monkeypatch.setattr(settings, "ENABLE_STEP_BACK_QUERY", True, raising=False)
    monkeypatch.setattr(settings, "STEP_BACK_TEMPERATURE", 0.0, raising=False)
    monkeypatch.setattr(settings, "STEP_BACK_MAX_CHARS", 200, raising=False)
    monkeypatch.setattr(settings, "STEP_BACK_OUTPUT_MAX_CHARS", 200, raising=False)

    # Avoid dict expansion noise.
    import app.query.expand as expand_mod

    monkeypatch.setattr(expand_mod, "load_base_dictionary_rules", lambda: [], raising=True)
    monkeypatch.setattr(
        expand_mod,
        "generate_dictionary_expansions",
        lambda **_k: ([], {"enabled": False, "used": False}),
        raising=True,
    )

    main_query = "BASE"
    step_back_query = "What general principles explain BASE?"

    engine = RAGEngine()
    engine.models["fast"] = FakeListChatModel(responses=[step_back_query])
    monkeypatch.setattr(orch_mod, "get_rag_engine", lambda: engine, raising=True)

    retriever = _RoutingRetriever(main_query=main_query, step_back_query=step_back_query)
    monkeypatch.setattr(orch_mod, "hybrid_retriever", retriever, raising=True)

    state = {
        "question": main_query,
        "history": None,
        "structured_output": False,
        "structured_preset": None,
        "top_k": 2,
        "score_threshold": 0.0,
        "retrieval_mode": "vector",
        "alpha": 0.6,
        "enable_weight_rerank": True,
        "vector_weight": 0.6,
        "keyword_weight": 0.4,
        "mmr_lambda": settings.RETRIEVAL_MMR_LAMBDA,
        "enable_reranker": False,
        "reranker_provider": "none",
        "reranker_top_n": 20,
        "tenant_id": uuid.uuid4(),
        "account_id": "u",
        "dataset_id": None,
        "document_ids": None,
        "metadata_filter": None,
        "metrics": {},
    }

    out = lg_mod._retrieve_node(state)  # type: ignore[arg-type]
    metrics = out.get("metrics") or {}
    assert metrics.get("step_back_enabled") is True
    assert metrics.get("step_back_used") is True
    assert metrics.get("step_back_parse_ok") is True
    assert metrics.get("step_back_parse_method") == "text"

    per_query = metrics.get("retrieval_per_query") or []
    assert any((x or {}).get("kind") == "step_back" for x in (per_query or []))

    query_debug = out.get("query_debug") or {}
    expansions = query_debug.get("expansions") or []
    assert any((e or {}).get("kind") == "step_back" for e in (expansions or []))

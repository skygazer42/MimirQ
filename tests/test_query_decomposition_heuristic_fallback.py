from __future__ import annotations

import uuid

import pytest


@pytest.mark.asyncio
async def test_engine_query_decomposition_heuristic_fallback_populates_subq_kinds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rag.engine as engine_mod
    from app.core.config import settings

    engine_mod.reset_rag_engine()

    # Keep the test deterministic / single-query.
    monkeypatch.setattr(settings, "ENABLE_QUERY_REWRITE", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_MULTI_QUERY", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_HYDE", False, raising=False)

    # Enable decomposition, but force "no LLM" mode.
    monkeypatch.setattr(settings, "ENABLE_QUERY_DECOMPOSITION", True, raising=False)
    monkeypatch.setattr(settings, "QUERY_DECOMPOSITION_MAX_SUBQUESTIONS", 3, raising=False)
    monkeypatch.setattr(settings, "QUERY_DECOMPOSITION_MIN_CHARS", 0, raising=False)
    monkeypatch.setattr(settings, "QUERY_DECOMPOSITION_MAX_CHARS", 400, raising=False)
    monkeypatch.setattr(settings, "QUERY_DECOMPOSITION_HEURISTIC_FALLBACK_ENABLED", True, raising=False)

    # Use deterministic fake LLM for generation (decomposition should not call it without API key).
    monkeypatch.setattr(settings, "LLM_API_KEY", "", raising=False)
    monkeypatch.setattr(settings, "LLM_MOCK_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "LLM_MOCK_RESPONSE", "OK", raising=False)

    # Avoid abstain path so we can inspect retrieval per-query kinds.
    monkeypatch.setattr(settings, "RAG_VISIBLE_EVIDENCE_ONLY_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "RAG_ABSTAIN_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "RETRIEVAL_QUERY_PARALLELISM", 1, raising=False)

    from langchain_core.documents import Document

    class _AnyDocRetriever:
        _last_debug_metrics = {}
        invoked: list[str] = []

        def model_copy(self, **_kwargs):  # noqa: ANN001, ANN002, ANN003
            return self

        def invoke(self, _q):  # noqa: ANN001
            self.invoked.append(str(_q or ""))
            return [
                Document(
                    page_content="alpha beta gamma",
                    metadata={
                        "source": "doc.txt",
                        "page": 1,
                        "score": 0.9,
                        "vector_score": 0.9,
                        "bm25_score": 0.1,
                    },
                    id=str(uuid.uuid4()),
                )
            ]

    retriever = _AnyDocRetriever()
    monkeypatch.setattr(engine_mod, "hybrid_retriever", retriever, raising=True)

    rag = engine_mod.get_rag_engine()
    agen = rag.stream_chat(
        question="Explain rate limits, and list retry headers; also show examples.",
        history=None,
        conversation_id=None,
        tenant_id=uuid.uuid4(),
        document_ids=None,
        account_id="u",
        top_k=1,
        score_threshold=0.0,
        retrieval_mode="vector",
        db=None,
    )

    done_data = None
    async for item in agen:
        if item.get("type") == "done":
            done_data = item.get("data") or {}
            break
    await agen.aclose()

    metrics = (done_data or {}).get("metrics") or {}
    assert metrics.get("decompose_used") is True
    assert metrics.get("decompose_parse_ok") is True
    assert metrics.get("decompose_parse_method") == "heuristic"

    assert "Explain rate limits" in (retriever.invoked or [])
    assert "list retry headers" in (retriever.invoked or [])
    assert "show examples" in (retriever.invoked or [])


def test_langgraph_query_decomposition_heuristic_fallback_populates_subq_kinds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rag.engine as engine_mod
    import app.rag.pipelines.langgraph as lg_mod
    import app.rag.retrieval.orchestrator as orch_mod
    from app.core.config import settings

    engine_mod.reset_rag_engine()

    monkeypatch.setattr(settings, "ENABLE_QUERY_REWRITE", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_MULTI_QUERY", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_HYDE", False, raising=False)

    monkeypatch.setattr(settings, "ENABLE_QUERY_DECOMPOSITION", True, raising=False)
    monkeypatch.setattr(settings, "QUERY_DECOMPOSITION_MAX_SUBQUESTIONS", 3, raising=False)
    monkeypatch.setattr(settings, "QUERY_DECOMPOSITION_MIN_CHARS", 0, raising=False)
    monkeypatch.setattr(settings, "QUERY_DECOMPOSITION_MAX_CHARS", 400, raising=False)
    monkeypatch.setattr(settings, "QUERY_DECOMPOSITION_HEURISTIC_FALLBACK_ENABLED", True, raising=False)

    monkeypatch.setattr(settings, "LLM_API_KEY", "", raising=False)

    from langchain_core.documents import Document

    class _AnyDocRetriever:
        _last_debug_metrics = {}

        def model_copy(self, **_kwargs):  # noqa: ANN001, ANN002, ANN003
            return self

        def invoke(self, _q):  # noqa: ANN001
            return [
                Document(
                    page_content="alpha beta gamma",
                    metadata={
                        "source": "doc.txt",
                        "page": 1,
                        "score": 0.9,
                        "vector_score": 0.9,
                        "bm25_score": 0.1,
                    },
                    id=str(uuid.uuid4()),
                )
            ]

    monkeypatch.setattr(orch_mod, "hybrid_retriever", _AnyDocRetriever(), raising=True)

    state = {
        "question": "Explain rate limits, and list retry headers; also show examples.",
        "history": None,
        "structured_output": False,
        "structured_preset": None,
        "top_k": 1,
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
    assert metrics.get("decompose_used") is True
    assert metrics.get("decompose_parse_ok") is True
    assert metrics.get("decompose_parse_method") == "heuristic"

    per_query = metrics.get("retrieval_per_query") or []
    assert any((x or {}).get("kind") == "subq" for x in (per_query or []))


def test_langgraph_query_decomposition_request_override_disables_global_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rag.engine as engine_mod
    import app.rag.pipelines.langgraph as lg_mod
    import app.rag.retrieval.orchestrator as orch_mod
    from app.core.config import settings

    engine_mod.reset_rag_engine()

    monkeypatch.setattr(settings, "ENABLE_QUERY_REWRITE", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_MULTI_QUERY", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_HYDE", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_QUERY_DECOMPOSITION", True, raising=False)
    monkeypatch.setattr(settings, "QUERY_DECOMPOSITION_MAX_SUBQUESTIONS", 3, raising=False)
    monkeypatch.setattr(settings, "QUERY_DECOMPOSITION_MIN_CHARS", 0, raising=False)
    monkeypatch.setattr(settings, "QUERY_DECOMPOSITION_MAX_CHARS", 400, raising=False)

    from langchain_core.documents import Document

    class _AnyDocRetriever:
        _last_debug_metrics = {}
        invoked: list[str] = []

        def model_copy(self, **_kwargs):  # noqa: ANN001, ANN002, ANN003
            return self

        def invoke(self, q):  # noqa: ANN001
            self.invoked.append(str(q or ""))
            return [
                Document(
                    page_content="alpha beta gamma",
                    metadata={"source": "doc.txt", "score": 0.9},
                    id=str(uuid.uuid4()),
                )
            ]

    retriever = _AnyDocRetriever()
    monkeypatch.setattr(orch_mod, "hybrid_retriever", retriever, raising=True)

    state = lg_mod.build_rag_state(
        question="Explain rate limits, and list retry headers; also show examples.",
        history=None,
        structured_output=False,
        structured_preset=None,
        top_k=1,
        score_threshold=0.0,
        retrieval_mode="vector",
        enable_query_decomposition=False,
        tenant_id=uuid.uuid4(),
        account_id="u",
        dataset_id=None,
        document_ids=None,
        metadata_filter=None,
        enable_reranker=False,
        reranker_provider="none",
    )

    out = lg_mod._retrieve_node(state)  # type: ignore[arg-type]
    metrics = out.get("metrics") or {}

    assert metrics.get("decompose_enabled") is False
    assert metrics.get("decompose_used") is False
    assert len(retriever.invoked) == 1
    assert retriever.invoked[0] == "Explain rate limits, and list retry headers; also show examples."

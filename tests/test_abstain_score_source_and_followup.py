from __future__ import annotations

import uuid

import pytest


@pytest.mark.asyncio
async def test_abstain_gate_uses_final_relevance_score_when_retrieval_score_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rag.engine as engine_mod
    from app.core.config import settings

    engine_mod.reset_rag_engine()

    # Keep deterministic / single-query.
    monkeypatch.setattr(settings, "ENABLE_QUERY_REWRITE", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_MULTI_QUERY", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_HYDE", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_QUERY_DECOMPOSITION", False, raising=False)

    # Deterministic fake LLM (not used beyond routing in abstain path).
    monkeypatch.setattr(settings, "LLM_API_KEY", "", raising=False)
    monkeypatch.setattr(settings, "LLM_MOCK_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "LLM_MOCK_RESPONSE", "SHOULD_NOT_APPEAR", raising=False)

    # Enable abstain based on top relevance score.
    monkeypatch.setattr(settings, "RAG_VISIBLE_EVIDENCE_ONLY_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "RAG_ABSTAIN_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "RAG_ABSTAIN_MIN_CITATIONS", 1, raising=False)
    monkeypatch.setattr(settings, "RAG_ABSTAIN_MIN_TOP_RELEVANCE_SCORE", 0.5, raising=False)

    from langchain_core.documents import Document

    class _OneLowScoreDocRetriever:
        _last_debug_metrics = {}

        def model_copy(self, **_kwargs):  # noqa: ANN001, ANN002, ANN003
            return self

        def invoke(self, _q):  # noqa: ANN001
            # Simulate reranking metadata: retrieval_score is high, but final relevance_score (score) is low.
            return [
                Document(
                    page_content="alpha beta gamma",
                    metadata={
                        "source": "doc.txt",
                        "page": 1,
                        "score": 0.1,  # relevance_score
                        "retrieval_score": 0.9,  # pre-rerank score (must NOT be used for abstain gate)
                        "vector_score": 0.1,
                        "bm25_score": 0.1,
                    },
                    id=str(uuid.uuid4()),
                )
            ]

    monkeypatch.setattr(engine_mod, "hybrid_retriever", _OneLowScoreDocRetriever(), raising=True)

    rag = engine_mod.get_rag_engine()
    agen = rag.stream_chat(
        question="What is X?",
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

    done_metrics = None
    async for item in agen:
        if item.get("type") == "done":
            done_metrics = (item.get("data") or {}).get("metrics") or {}
            break
    await agen.aclose()

    assert (done_metrics or {}).get("abstain_triggered") is True
    assert (done_metrics or {}).get("abstain_reason") == "top_relevance_lt_min"
    assert float((done_metrics or {}).get("top_relevance_score") or 0.0) == pytest.approx(0.1)

    followup = (done_metrics or {}).get("abstain_followup")
    assert isinstance(followup, dict)
    assert isinstance(followup.get("question"), str) and followup.get("question")
    assert isinstance(followup.get("options"), list)


def test_langgraph_retrieve_node_abstain_gate_uses_final_relevance_score_and_sets_followup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rag.engine as engine_mod
    import app.rag.pipelines.langgraph as lg_mod
    import app.rag.retrieval.orchestrator as orch_mod
    from app.core.config import settings

    engine_mod.reset_rag_engine()

    # Keep deterministic / single-query.
    monkeypatch.setattr(settings, "ENABLE_QUERY_REWRITE", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_MULTI_QUERY", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_HYDE", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_QUERY_DECOMPOSITION", False, raising=False)

    monkeypatch.setattr(settings, "RAG_VISIBLE_EVIDENCE_ONLY_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "RAG_ABSTAIN_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "RAG_ABSTAIN_MIN_CITATIONS", 1, raising=False)
    monkeypatch.setattr(settings, "RAG_ABSTAIN_MIN_TOP_RELEVANCE_SCORE", 0.5, raising=False)

    from langchain_core.documents import Document

    class _OneLowScoreDocRetriever:
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
                        "score": 0.1,
                        "retrieval_score": 0.9,
                        "vector_score": 0.1,
                        "bm25_score": 0.1,
                    },
                    id=str(uuid.uuid4()),
                )
            ]

    monkeypatch.setattr(orch_mod, "hybrid_retriever", _OneLowScoreDocRetriever(), raising=True)

    state = {
        "question": "What is X?",
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
    assert out.get("abstain_triggered") is True
    assert metrics.get("abstain_reason") == "top_relevance_lt_min"
    assert float(metrics.get("top_relevance_score") or 0.0) == pytest.approx(0.1)
    followup = metrics.get("abstain_followup")
    assert isinstance(followup, dict)
    assert isinstance(followup.get("question"), str) and followup.get("question")
    assert isinstance(followup.get("options"), list)

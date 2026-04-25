from __future__ import annotations

from app.rag.reranker.llm_based import (
    LLMReranker,
    _finalize_rerank_scores,
    resolve_llm_reranker_weight,
)


def test_finalize_rerank_scores_combines_llm_and_vector_anchor() -> None:
    ordered, score_map = _finalize_rerank_scores(
        candidates=[
            {"id": "doc-a", "score": 0.2},
            {"id": "doc-b", "score": 0.9},
        ],
        llm_scores={"doc-a": 1.0, "doc-b": 0.0},
        llm_weight=0.7,
    )

    assert ordered == ["doc-a", "doc-b"]
    assert score_map["doc-a"] > score_map["doc-b"]
    assert score_map["doc-a"] == 0.76
    assert score_map["doc-b"] == 0.27


def test_llm_rerank_raw_falls_back_to_vector_anchor_when_llm_output_is_invalid() -> None:
    reranker = LLMReranker.__new__(LLMReranker)
    reranker.model_used = "stub"
    reranker.llm_weight = 0.7
    reranker.fallback_score = 0.5
    reranker._chain = type("_BadChain", (), {"invoke": lambda self, _payload: "not-json"})()

    result = reranker.rerank_raw(
        query="Which chunk is more relevant?",
        candidates=[
            {"id": "doc-a", "text": "alpha", "score": 0.2},
            {"id": "doc-b", "text": "beta", "score": 0.9},
        ],
    )

    assert result.ordered_ids == ["doc-b", "doc-a"]
    assert result.score_map["doc-b"] == 0.9
    assert result.score_map["doc-a"] == 0.2


def test_finalize_rerank_scores_backfills_missing_llm_scores_with_default_score() -> None:
    ordered, score_map = _finalize_rerank_scores(
        candidates=[
            {"id": "doc-a", "score": 0.2},
            {"id": "doc-b", "score": 0.9},
        ],
        llm_scores={"doc-a": 1.0},
        llm_weight=0.7,
        fallback_score=0.5,
    )

    assert ordered == ["doc-a", "doc-b"]
    assert score_map["doc-a"] == 0.76
    assert score_map["doc-b"] == 0.62


def test_resolve_llm_reranker_weight_supports_tenant_and_query_type_overrides(monkeypatch) -> None:  # noqa: ANN001
    from app.core.config import settings

    monkeypatch.setattr(settings, "RERANKER_LLM_WEIGHT", 0.7, raising=False)
    monkeypatch.setattr(
        settings,
        "RERANKER_LLM_WEIGHT_BY_TENANT",
        '{"tenant-a": 0.3, "tenant-b": 0.8}',
        raising=False,
    )
    monkeypatch.setattr(
        settings,
        "RERANKER_LLM_WEIGHT_BY_QUERY_TYPE",
        '{"factual": 0.4, "multi_hop": 0.85}',
        raising=False,
    )

    assert resolve_llm_reranker_weight(tenant_id="tenant-a", query_type=None) == 0.3
    assert resolve_llm_reranker_weight(tenant_id=None, query_type="multi_hop") == 0.85
    # tenant override should win when both are present
    assert resolve_llm_reranker_weight(tenant_id="tenant-b", query_type="factual") == 0.8
    assert resolve_llm_reranker_weight(tenant_id=None, query_type=None) == 0.7

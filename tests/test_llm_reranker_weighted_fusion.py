from __future__ import annotations

from app.rag.reranker.llm_based import LLMReranker, _finalize_rerank_scores


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

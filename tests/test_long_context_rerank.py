from __future__ import annotations

from app.rag.reranker.long_context_rerank import rerank_long_context_candidates
from app.rag.reranker.types import RerankCandidate


def test_rerank_long_context_candidates_returns_unified_result_shape() -> None:
    candidates = [
        RerankCandidate(id="c1", text="关于知识产权的前四项定义", metadata={"chunk_index": 1}),
        RerankCandidate(id="c2", text="关于知识产权的后四项定义", metadata={"chunk_index": 2}),
    ]

    result = rerank_long_context_candidates(
        query="根据知识产权定义，哪些对象可享有专有权利？",
        candidates=candidates,
        scorer=lambda _query, docs: {doc.id: 1.0 - idx * 0.1 for idx, doc in enumerate(docs)},
        top_n=2,
    )

    assert result.ordered_ids == ["c1", "c2"]
    assert result.score_map["c1"] == 1.0
    assert result.stats["mode"] == "long_context"
    assert result.stats["candidates_considered"] == 2

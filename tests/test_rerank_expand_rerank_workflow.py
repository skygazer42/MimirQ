from __future__ import annotations

from app.rag.reranker.types import RerankCandidate, RerankResult
from app.rag.workflows.rerank_expand_rerank import run_rerank_expand_rerank


def test_run_rerank_expand_rerank_runs_two_passes_and_merges_expanded_candidates() -> None:
    candidates = [
        RerankCandidate(id="c1", text="块1", metadata={"chunk_index": 1}),
        RerankCandidate(id="c2", text="块2", metadata={"chunk_index": 2}),
    ]

    def _rerank(query: str, docs: list[RerankCandidate], **_kwargs) -> RerankResult:  # noqa: ARG001
        scores = {"c1": 0.9, "c2": 0.5, "c3": 0.8, "c4": 0.7}
        ordered = sorted([doc.id for doc in docs], key=lambda cid: scores.get(cid, 0.0), reverse=True)
        return RerankResult(
            ordered_ids=ordered,
            score_map={cid: scores.get(cid, 0.0) for cid in ordered},
            stats={"provider": "test"},
        )

    catalog = {
        "c1": candidates[0],
        "c2": candidates[1],
        "c3": RerankCandidate(id="c3", text="块3", metadata={"chunk_index": 3}),
        "c4": RerankCandidate(id="c4", text="块4", metadata={"chunk_index": 4}),
    }

    result = run_rerank_expand_rerank(
        query="作文全文是什么？",
        candidates=candidates,
        rerank_fn=_rerank,
        get_adjacent_ids=lambda cid, span: [f"c{int(cid[1:]) + offset}" for offset in range(1, span + 1) if f"c{int(cid[1:]) + offset}" in catalog],
        resolve_candidate=lambda cid: catalog[cid],
        top_n=4,
    )

    assert result.ordered_ids[:4] == ["c1", "c3", "c4", "c2"]
    assert result.stats["expanded_candidate_count"] == 4
    assert result.stats["first_pass_top_ids"] == ["c1", "c2"]
    assert result.stats["second_pass"] is True

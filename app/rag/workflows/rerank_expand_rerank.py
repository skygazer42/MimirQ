from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from app.rag.retrieval.neighbor_expand import expand_neighbors_by_score
from app.rag.reranker.types import RerankCandidate, RerankResult


def run_rerank_expand_rerank(
    *,
    query: str,
    candidates: Sequence[RerankCandidate],
    rerank_fn: Callable[..., RerankResult],
    get_adjacent_ids: Callable[[str, int], list[str]],
    resolve_candidate: Callable[[str], RerankCandidate],
    top_n: int = 20,
    high_threshold: float = 0.7,
    mid_threshold: float = 0.4,
    high_span: int = 3,
    mid_span: int = 1,
) -> RerankResult:
    base_candidates = list(candidates or [])
    first_pass = rerank_fn(str(query or ""), base_candidates, top_n=max(1, int(top_n or 1)))
    first_ranked = [
        {"id": cid, "score": float(first_pass.score_map.get(cid, 0.0))}
        for cid in first_pass.ordered_ids
    ]
    expanded = expand_neighbors_by_score(
        ranked_items=first_ranked,
        get_adjacent_ids=get_adjacent_ids,
        high_threshold=high_threshold,
        mid_threshold=mid_threshold,
        high_span=high_span,
        mid_span=mid_span,
    )
    expanded_ids = list(expanded["expanded_ids"])
    expanded_candidates = [resolve_candidate(cid) for cid in expanded_ids]
    second_pass = rerank_fn(str(query or ""), expanded_candidates, top_n=max(1, int(top_n or 1)))
    second_pass.stats = {
        **dict(second_pass.stats or {}),
        "first_pass_top_ids": list(first_pass.ordered_ids),
        "expanded_candidate_count": len(expanded_candidates),
        "second_pass": True,
    }
    return second_pass

from collections.abc import Callable, Sequence

from app.rag.retrieval.expansion.neighbors import expand_neighbors_by_score
from app.rag.retrieval.reranking.types import RerankCandidate, RerankResult


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
    base_candidates = list(candidates)
    bounded_top_n = max(1, top_n)
    first_pass = rerank_fn(query, base_candidates, top_n=bounded_top_n)
    first_ranked = [{"id": cid, "score": first_pass.score_map[cid]} for cid in first_pass.ordered_ids]
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
    second_pass = rerank_fn(query, expanded_candidates, top_n=bounded_top_n)
    second_pass.stats = {
        **second_pass.stats,
        "first_pass_top_ids": list(first_pass.ordered_ids),
        "expanded_candidate_count": len(expanded_candidates),
        "second_pass": True,
    }
    return second_pass

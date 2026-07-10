
from app.rag.reranker.types import RerankCandidate


def test_mmr_reranker_prefers_relevant_but_diverse_candidates() -> None:
    from app.rag.reranker.mmr import MMRReranker

    reranker = MMRReranker(lambda_mult=0.5)
    candidates = [
        RerankCandidate(id="a", text="mqtt keepalive setting for broker"),
        RerankCandidate(id="b", text="mqtt keepalive configuration for broker"),
        RerankCandidate(id="c", text="license activation troubleshooting steps"),
    ]

    out = reranker.rerank("mqtt keepalive", candidates, top_n=2)

    assert out.ordered_ids[0] == "a"
    assert out.ordered_ids[1] == "c"
    assert out.provider == "mmr"


def test_factory_resolves_mmr_provider() -> None:
    from app.rag.reranker.factory import describe_reranker_provider, get_reranker

    inst = get_reranker("mmr")
    assert inst.__class__.__name__ == "MMRReranker"
    assert describe_reranker_provider("mmr")["tier"] == "prod"

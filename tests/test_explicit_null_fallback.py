import pytest

from app.rag.retrieval.reranking.types import RerankCandidate


def test_falsy_long_context_scorer_is_used() -> None:
    from app.rag.retrieval.reranking.long_context import LongContextReranker

    class Scorer:
        def __init__(self):
            self.calls = []

        def __bool__(self) -> bool:
            return False

        def __call__(self, query, candidates):
            self.calls.append(query)
            return {candidate.id: float(index) for index, candidate in enumerate(candidates)}

    scorer = Scorer()
    result = LongContextReranker(scorer=scorer).rerank(
        "unrelated", [RerankCandidate(id="first", text="one"), RerankCandidate(id="second", text="two")]
    )
    assert result.ordered_ids == ["second", "first"]
    assert scorer.calls == ["unrelated"]


def test_explicit_zero_burst_does_not_enable_the_default_capacity() -> None:
    from app.api.middleware.rate_limit import RateLimiter

    limiter = RateLimiter(requests_per_second=10, burst_size=0)
    assert limiter.burst_size == 0
    assert limiter.check("client")[0] is False


def test_redis_limiter_preserves_explicit_zero_burst_without_connecting() -> None:
    from app.api.middleware.rate_limit import RedisRateLimiter

    limiter = RedisRateLimiter(redis_url="redis://unused", namespace="test", burst_size=0)
    assert limiter.burst_size == 0


@pytest.mark.parametrize("value,expected", [(None, None), (0, "0"), (False, "false"), ("", None), (" value ", "value")])
def test_optional_override_normalization_keeps_zero_and_false(value, expected) -> None:
    from app.services.pipelines.ingestion_policy import _normalize_optional_override

    assert _normalize_optional_override(value) == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("provided", [False, True])
async def test_lazy_summary_creates_a_client_only_when_missing(monkeypatch, provided) -> None:
    from app.rag.kg.search import searcher

    class Client:
        def __bool__(self) -> bool:
            return False

    client = Client()
    created = []

    async def create_client(**kwargs):
        created.append(kwargs)
        return client

    async def summarize(**kwargs):
        assert kwargs["llm_client"] is client
        return "summary"

    monkeypatch.setattr(searcher, "create_llm_client", create_client)
    monkeypatch.setattr(searcher, "lazy_summarize", summarize)
    report = {}
    meta = {"enabled": True, "used": True, "cache_hits": 0, "generated": 0, "errors": 0}
    result = await searcher._generate_lazy_summary(
        llm_client=client if provided else None,
        report=report,
        query="query",
        max_tokens=64,
        cache_enabled=False,
        cache_key="test",
        ttl_sec=0,
        max_entries=1,
        meta=meta,
    )
    assert result is client
    assert len(created) == (0 if provided else 1)
    assert report["llm_summary"] == "summary"
    assert meta["generated"] == 1

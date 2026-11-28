from types import SimpleNamespace

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


@pytest.mark.parametrize(
    "value,expected", [(None, None), ("0", "0"), ("False", "false"), ("", None), (" value ", "value")]
)
def test_optional_string_override_normalization_keeps_nonempty_values(value, expected) -> None:
    from app.services.pipelines.ingestion_policy import _normalize_optional_override

    assert _normalize_optional_override(value) == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("cached", [False, True])
async def test_lazy_summary_creates_one_client_for_uncached_reports(monkeypatch, cached) -> None:
    from app.rag.kg.search import searcher

    calls = []

    class Client:
        def __bool__(self) -> bool:
            return False

        async def aclose(self) -> None:
            calls.append("close")

    client = Client()

    async def create_client():
        calls.append("create")
        return client

    async def summarize(**kwargs):
        assert kwargs["llm_client"] is client
        calls.append("summarize")
        return "summary"

    monkeypatch.setattr(
        searcher,
        "_lazy_community_summary_settings",
        lambda: {"enabled": True, "top_n": 2, "max_tokens": 64, "ttl_sec": 60, "max_entries": 2},
    )
    monkeypatch.setattr(
        searcher,
        "kg_community_summary_cache",
        SimpleNamespace(
            get=lambda *_args, **_kwargs: ("summary" if cached else None, 0), set=lambda *_args, **_kwargs: None
        ),
    )
    monkeypatch.setattr(searcher, "create_llm_client", create_client)
    monkeypatch.setattr(searcher, "lazy_summarize", summarize)
    reports = [{"community_id": "one"}, {"community_id": "two"}]
    meta = await searcher._apply_lazy_community_summaries(
        config=searcher.SearchConfig(query="query"),
        reports=reports,
        query="query",
    )
    assert calls == ([] if cached else ["create", "summarize", "summarize", "close"])
    assert [report["llm_summary"] for report in reports] == ["summary", "summary"]
    assert meta["cache_hits"] == (2 if cached else 0)
    assert meta["generated"] == (0 if cached else 2)
    assert meta["errors"] == 0

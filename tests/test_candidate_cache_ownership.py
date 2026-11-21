import asyncio
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest


@pytest.fixture
def cache_run(monkeypatch: pytest.MonkeyPatch):
    from app.infrastructure.config import settings
    from app.rag.retrieval.cache import candidates as cache_api
    from app.rag.retrieval.configuration.options import HybridSearchOptions
    from app.rag.retrieval.corpus import CorpusIndex
    from app.rag.retrieval.recall.candidate_retrieval import CandidateRequest
    from app.rag.retrieval.recall.runtime_scope import ResolvedRetrievalScope, RetrievalScope, RuntimeShard
    from app.services.datasets.embedding_config import DatasetEmbeddingRuntimeConfig
    from app.services.retrieval import semantic_cache

    for name, value in {
        "RETRIEVAL_CANDIDATE_CACHE_ENABLED": True,
        "RETRIEVAL_CANDIDATE_CACHE_TTL_SEC": 30,
        "RETRIEVAL_CANDIDATE_SINGLEFLIGHT_ENABLED": True,
        "SEMANTIC_CACHE_ENABLED": True,
        "SEMANTIC_CACHE_TTL_SEC": 30,
    }.items():
        monkeypatch.setattr(settings, name, value)
    cache_api.clear_inflight_retrieval_candidates()
    runtime = DatasetEmbeddingRuntimeConfig(
        provider="local",
        model="test",
        api_base="",
        api_key="",
        embedding_space_hash="space",
        collection_name="documents",
        dataset_scoped=False,
    )
    tenant_id, dataset_id = uuid4(), uuid4()
    scope = RetrievalScope(tenant_id=tenant_id, account_id="account-a", dataset_ids=(dataset_id,))
    resolved = ResolvedRetrievalScope(
        scope=scope,
        runtime_dataset_ids=(dataset_id,),
        runtime_shards=(RuntimeShard(runtime, (dataset_id,)),),
        runtime=runtime,
        metadata_filter={"dataset_id": str(dataset_id)},
        keyword_filter={"dataset_id": str(dataset_id)},
        vector_filter=None,
        has_unscoped_documents=False,
    )
    request = CandidateRequest(
        query="query",
        options=HybridSearchOptions(top_k=2, tenant_id=tenant_id),
        resolved_scope=resolved,
        behavior_hash="behavior",
    )
    corpus = CorpusIndex(bm25_store=object())
    monkeypatch.setattr(corpus, "resolve_version", lambda scope: "version")
    order = []
    monkeypatch.setattr(cache_api, "get_cached_retrieval_candidates", lambda key: None)
    monkeypatch.setattr(
        cache_api, "set_cached_retrieval_candidates", lambda key, payload: order.append("exact") or True
    )
    monkeypatch.setattr(
        cache_api,
        "publish_distributed_inflight_retrieval_candidates",
        lambda key, payload: order.append("publish") or True,
    )
    monkeypatch.setattr(
        cache_api,
        "acquire_or_wait_for_distributed_inflight_retrieval_candidates",
        lambda key: (True, None, cache_api._DistributedRetrievalLease(key + ":lease", "owner")),
    )
    monkeypatch.setattr(
        cache_api, "release_distributed_inflight_retrieval_candidates", lambda lease: order.append("release")
    )
    monkeypatch.setattr(semantic_cache, "get_cached_semantic_payload", lambda **kwargs: (None, {}))
    monkeypatch.setattr(
        semantic_cache, "set_cached_semantic_payload", lambda **kwargs: order.append("semantic") or True
    )
    yield request, corpus, cache_api, order
    cache_api.clear_inflight_retrieval_candidates()


def test_cache_owner_preserves_exact_publish_release_semantic_order(cache_run) -> None:
    from app.rag.retrieval.recall.candidate_retrieval import CandidateCacheSession

    request, corpus, cache_api, order = cache_run
    payload = [{"chunk_id": "chunk", "content": "result"}]
    with CandidateCacheSession(request, corpus_index=corpus) as cache:
        assert cache.lookup() is None
        key = cache.key
        cache.publish(payload, degraded=False)
    assert order == ["exact", "publish", "release", "semantic"]
    assert key not in cache_api._inflight_candidate_futures
    outcome = cache.outcome
    assert outcome.metadata["store_ok"] is True
    assert outcome.metadata["semantic"]["store_ok"] is True
    assert outcome.source == "computed"


def test_exact_hit_returns_its_limit_without_acquiring_a_flight(cache_run, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.rag.retrieval.recall.candidate_retrieval import CandidateCacheSession

    request, corpus, cache_api, order = cache_run
    payload = [{"content": "first"}, {"content": "second"}, {"content": "third"}]
    monkeypatch.setattr(cache_api, "get_cached_retrieval_candidates", lambda key: payload)
    monkeypatch.setattr(
        cache_api, "acquire_inflight_retrieval_candidates", lambda key: pytest.fail("cache hit acquired a flight")
    )
    with CandidateCacheSession(request, corpus_index=corpus) as cache:
        assert cache.lookup() == payload[:2]
    assert order == []
    assert cache.outcome.source == "exact"
    assert cache.outcome.metadata["hit"] is True


def _candidate_policies():
    from app.rag.retrieval.ranking.candidates import (
        DedupPolicy,
        DiversityPolicy,
        FusionPolicy,
        RankingPolicy,
        RerankPolicy,
    )
    from app.rag.retrieval.recall.channel_collection import ChannelPolicy

    channels = ChannelPolicy(
        bm25_enabled=True,
        lexical_enabled=False,
        keyword_bm25_secondary_enabled=False,
        lexical_hybrid_fallback_only=True,
        lexical_metadata_exact_fallback_enabled=False,
        metadata_exact_db_enabled=False,
    )
    ranking = RankingPolicy(
        FusionPolicy("rrf", 60),
        DedupPolicy(False, 0.9, 100, 0),
        DiversityPolicy(0, 0, 0),
        RerankPolicy(False, "llm", 20),
    )
    return channels, ranking


def test_complete_candidate_operation_owns_recall_ranking_and_publication_order(cache_run, monkeypatch):
    from app.rag.retrieval.corpus import CorpusSearchResult
    from app.rag.retrieval.ranking import candidates as candidate_ranking
    from app.rag.retrieval.recall import candidate_retrieval

    request, corpus, cache_api, order = cache_run
    request = replace(request, options=replace(request.options, retrieval_mode="keyword", enable_weight_rerank=False))
    payload = [
        {"chunk_id": value, "content": value, "score": 1.0, "metadata": {"document_id": "document"}}
        for value in ("b", "a", "c")
    ]

    def search(*args, **kwargs):
        order.append("channels")
        return CorpusSearchResult(payload, {"reason": "ok"})

    rank = candidate_ranking.rank_candidates

    def rank_actual(*args, **kwargs):
        order.append("ranking")
        return rank(*args, **kwargs)

    monkeypatch.setattr(corpus, "search", search)
    monkeypatch.setattr(corpus, "chunk_id_lookup", lambda scope, *, candidates: {})
    monkeypatch.setattr(candidate_ranking, "rank_candidates", rank_actual)
    channels, ranking = _candidate_policies()
    batch = candidate_retrieval.retrieve_candidates(
        request, channel_policy=channels, ranking_policy=ranking, corpus_index=corpus
    )
    assert batch.failure is None
    assert [item["chunk_id"] for item in batch.candidates] == ["a", "b"]
    assert batch.resolved_scope is request.resolved_scope
    assert batch.ranking.channels.bm25_results == payload
    assert batch.channel_metrics["counts"]["bm25_candidates"] == 3
    assert batch.cache.source == "computed"
    assert order == ["channels", "ranking", "exact", "publish", "release", "semantic"]
    assert cache_api._inflight_candidate_futures == {}


def test_complete_candidate_cache_hit_skips_channel_and_ranking_dependencies(cache_run, monkeypatch):
    from app.rag.retrieval.recall import candidate_retrieval, channel_collection

    request, corpus, cache_api, order = cache_run
    payload = [{"content": "cached"}]
    monkeypatch.setattr(cache_api, "get_cached_retrieval_candidates", lambda key: payload)

    def unused(*args, **kwargs):
        raise AssertionError("cache hit ran recall")

    monkeypatch.setattr(channel_collection, "collect_channels", unused)
    channels, ranking = _candidate_policies()
    batch = candidate_retrieval.retrieve_candidates(
        request, channel_policy=channels, ranking_policy=ranking, corpus_index=corpus
    )
    assert batch.failure is None and batch.candidates == payload
    assert batch.collection is batch.ranking is None
    assert batch.cache.source == "exact"
    assert batch.resolved_scope is request.resolved_scope
    assert order == []


@pytest.mark.parametrize("cancelled", [False, True])
def test_complete_candidate_failure_cleans_up_its_owned_lease(cache_run, monkeypatch, cancelled):
    from app.rag.retrieval.recall import candidate_retrieval, channel_collection

    request, corpus, cache_api, order = cache_run
    failure = asyncio.CancelledError("cancelled") if cancelled else RuntimeError("channel operation failed")

    def fail(*args, **kwargs):
        assert len(cache_api._inflight_candidate_futures) == 1
        raise failure

    monkeypatch.setattr(channel_collection, "collect_channels", fail)
    channels, ranking = _candidate_policies()
    if cancelled:
        with pytest.raises(asyncio.CancelledError) as caught:
            candidate_retrieval.retrieve_candidates(
                request, channel_policy=channels, ranking_policy=ranking, corpus_index=corpus
            )
        assert caught.value is failure
    else:
        batch = candidate_retrieval.retrieve_candidates(
            request, channel_policy=channels, ranking_policy=ranking, corpus_index=corpus
        )
        assert batch.failure is failure and batch.candidates == []
    assert order == ["release"]
    assert cache_api._inflight_candidate_futures == {}


def test_cache_operation_executes_without_importing_the_reader_adapter() -> None:
    script = """
import importlib.abc
import sys
from uuid import uuid4
class NoReader(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'app.rag.retrieval.recall.retriever':
            raise AssertionError('Cache owner imports reader')
sys.meta_path.insert(0, NoReader())
from app.infrastructure.config import settings
from app.rag.retrieval.corpus import CorpusIndex
from app.rag.retrieval.recall.candidate_retrieval import CandidateCacheSession, CandidateRequest
from app.rag.retrieval.recall.runtime_scope import RetrievalScope, resolve_runtime_scope
from app.rag.retrieval.configuration.options import HybridSearchOptions
from app.services.datasets.embedding_config import DatasetEmbeddingRuntimeConfig
settings.RETRIEVAL_CANDIDATE_CACHE_ENABLED = False
settings.RETRIEVAL_CANDIDATE_SINGLEFLIGHT_ENABLED = False
settings.SEMANTIC_CACHE_ENABLED = False
runtime = DatasetEmbeddingRuntimeConfig('local', 'test', '', '', 'space', 'documents', False)
scope = resolve_runtime_scope(object(), scope=RetrievalScope(uuid4(), 'actor'), embedding_runtime=runtime)
request = CandidateRequest('query', HybridSearchOptions(), scope, None)
with CandidateCacheSession(request, corpus_index=CorpusIndex(bm25_store=object())) as cache:
    assert cache.lookup() is None
    cache.publish([], degraded=False)
assert cache.outcome.metadata['enabled'] is False
assert 'app.rag.retrieval.recall.retriever' not in sys.modules
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("failure", [RuntimeError("channel failed"), asyncio.CancelledError()])
def test_cache_owner_releases_lease_and_rejects_its_future_on_failure(cache_run, failure) -> None:
    from app.rag.retrieval.recall.candidate_retrieval import CandidateCacheSession

    request, corpus, cache_api, order = cache_run
    with pytest.raises(type(failure)) as caught:
        with CandidateCacheSession(request, corpus_index=corpus) as cache:
            assert cache.lookup() is None
            key = cache.key
            leader, future = cache_api.acquire_inflight_retrieval_candidates(key)
            assert leader is False
            raise failure
    assert caught.value is failure
    assert order == ["release"]
    assert key not in cache_api._inflight_candidate_futures
    assert future.exception() is failure


def test_follower_timeout_does_not_reject_the_active_leaders_future(cache_run, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.rag.retrieval.recall.candidate_retrieval import CandidateCacheSession

    request, corpus, cache_api, order = cache_run
    with CandidateCacheSession(request, corpus_index=corpus) as leader:
        assert leader.lookup() is None
        future = cache_api._inflight_candidate_futures[leader.key]

        def timeout(*_args, **_kwargs):
            raise cache_api.RetrievalCandidateSingleflightTimeoutError(1)

        monkeypatch.setattr(cache_api, "wait_for_inflight_retrieval_candidates", timeout)
        with pytest.raises(cache_api.RetrievalCandidateSingleflightTimeoutError):
            with CandidateCacheSession(request, corpus_index=corpus) as follower:
                follower.lookup()
        assert cache_api._inflight_candidate_futures[leader.key] is future
        assert not future.done()
        leader.publish([], degraded=False)
    assert future.result() == []
    assert order == ["publish", "release"]


def test_leader_context_without_a_published_result_fails_and_releases_its_resources(cache_run) -> None:
    from app.rag.retrieval.recall.candidate_retrieval import CandidateCacheSession

    request, corpus, cache_api, order = cache_run
    with pytest.raises(RuntimeError, match="ended before publishing"):
        with CandidateCacheSession(request, corpus_index=corpus) as cache:
            assert cache.lookup() is None
            future = cache_api._inflight_candidate_futures[cache.key]
    assert cache_api._inflight_candidate_futures == {}
    assert str(future.exception()) == "Candidate retrieval ended before publishing a result"
    assert order == ["release"]


def test_overlapping_accounts_have_separate_cache_keys_and_outcomes(cache_run) -> None:
    from app.rag.retrieval.recall.candidate_retrieval import CandidateCacheSession

    request, corpus, cache_api, order = cache_run
    second_request = replace(
        request,
        resolved_scope=replace(
            request.resolved_scope, scope=replace(request.resolved_scope.scope, account_id="account-b")
        ),
    )
    with CandidateCacheSession(request, corpus_index=corpus) as first:
        assert first.lookup() is None
        with CandidateCacheSession(second_request, corpus_index=corpus) as second:
            assert second.lookup() is None
            assert first.key != second.key
            first.publish([{"content": "first"}], degraded=False)
            second.publish([{"content": "partial"}], degraded=True)
    first_outcome, second_outcome = first.outcome, second.outcome
    assert first_outcome.metadata["store_ok"] is True
    assert second_outcome.metadata["store_skip_reason"] == "retrieval_degraded"
    first_outcome.metadata["semantic"]["hit"] = True
    assert second_outcome.metadata["semantic"]["hit"] is False
    assert cache_api._inflight_candidate_futures == {}

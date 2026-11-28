import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4


def _request(mode="keyword", query="query"):
    from app.rag.retrieval.configuration.options import HybridSearchOptions
    from app.rag.retrieval.recall.channel_collection import ChannelRequest
    from app.rag.retrieval.recall.runtime_scope import ResolvedRetrievalScope, RetrievalScope
    from app.services.datasets.embedding_config import DatasetEmbeddingRuntimeConfig

    scope = RetrievalScope(uuid4(), "actor")
    runtime = DatasetEmbeddingRuntimeConfig("local", "test", "", "", "space", "documents", False)
    resolved = ResolvedRetrievalScope(scope, (), (), runtime, None, None, None, False)
    return ChannelRequest(query, HybridSearchOptions(top_k=2, retrieval_mode=mode, tenant_id=scope.tenant_id), resolved)


def _policy(**changes):
    from app.rag.retrieval.recall.channel_collection import ChannelPolicy

    return replace(
        ChannelPolicy(
            bm25_enabled=True,
            lexical_enabled=True,
            keyword_bm25_secondary_enabled=False,
            lexical_hybrid_fallback_only=True,
            lexical_metadata_exact_fallback_enabled=False,
            metadata_exact_db_enabled=False,
        ),
        **changes,
    )


def _corpus(monkeypatch, search):
    from app.rag.retrieval.corpus import CorpusIndex

    owner = CorpusIndex(bm25_store=object())
    monkeypatch.setattr(owner, "search", search)
    return owner


def test_keyword_failure_keeps_original_error_and_runs_bm25_before_vector(monkeypatch):
    from app.rag.retrieval.corpus import CorpusSearchResult
    from app.rag.retrieval.recall import channel_collection, lexical_search

    request = _request()
    failure = ConnectionError("lexical unavailable")
    calls = []

    def lexical(db, request, **kwargs):
        calls.append("lexical")
        return lexical_search.LexicalOutcome([], None, failure)

    def bm25(query, **kwargs):
        calls.append("bm25")
        assert kwargs["scope"].tenant_id == request.resolved_scope.scope.tenant_id
        return CorpusSearchResult([{"content": "kept", "metadata": {}, "score": 0.9}], {"reason": "ok"})

    monkeypatch.setattr(lexical_search, "search_lexical", lexical)
    batch = channel_collection.collect_channels(
        request, policy=_policy(), corpus_index=_corpus(monkeypatch, bm25), vector_store=object()
    )
    assert calls == ["lexical", "bm25"]
    assert batch.keyword.lexical.failure is failure
    assert batch.channels.bm25_results[0]["content"] == "kept"
    metrics = {}
    batch.health.publish(metrics)
    assert metrics["successful_channels"] == ["bm25"]
    assert metrics["degraded_reasons"] == [{"channel": "lexical_db", "error_type": "ConnectionError"}]


def test_partial_vector_timeout_keeps_hits_and_attempts_the_existing_fallback_order(monkeypatch):
    from app.rag.retrieval.corpus import CorpusSearchResult
    from app.rag.retrieval.recall import channel_collection, lexical_search, vector_search
    from app.rag.retrieval.recall.runtime_scope import RuntimeShard
    from app.services.runtime.retrieval_limiter import RetrievalAdmissionTimeoutError

    request = _request("vector")
    runtime = request.resolved_scope.runtime
    shards = tuple(RuntimeShard(runtime, (uuid4(),)) for _ in range(2))
    request = replace(request, resolved_scope=replace(request.resolved_scope, runtime_shards=shards))
    failure = RetrievalAdmissionTimeoutError(0.01)
    calls = []
    kept = {"content": "kept", "metadata": {}, "score": 0.9}

    def vectors(*args, **kwargs):
        calls.append("vector")
        return vector_search.VectorSearchBatch(
            [kept],
            (
                vector_search.VectorShardResult(shards[0], [kept], None),
                vector_search.VectorShardResult(shards[1], [], failure),
            ),
        )

    def bm25(query, **kwargs):
        calls.append("bm25")
        return CorpusSearchResult([], {"reason": "empty"})

    def lexical(db, request, **kwargs):
        calls.append("lexical")
        return lexical_search.LexicalOutcome([], False, None)

    monkeypatch.setattr(vector_search, "search_vectors", vectors)
    monkeypatch.setattr(lexical_search, "search_lexical", lexical)
    batch = channel_collection.collect_channels(
        request, policy=_policy(), corpus_index=_corpus(monkeypatch, bm25), vector_store=object()
    )
    assert calls == ["vector", "bm25", "lexical"]
    assert batch.channels.vector_results == [kept]
    assert batch.vector.batch.failures == (failure,)
    assert batch.failure is None
    metrics = {}
    batch.health.publish(metrics)
    assert metrics["retrieval_degraded"] is True
    assert metrics["all_retrieval_channels_failed"] is False


def test_empty_fallbacks_preserve_the_original_vector_admission_timeout(monkeypatch):
    from app.rag.retrieval.corpus import CorpusSearchResult
    from app.rag.retrieval.recall import channel_collection, lexical_search, vector_search
    from app.rag.retrieval.recall.runtime_scope import RuntimeShard
    from app.services.runtime.retrieval_limiter import RetrievalAdmissionTimeoutError

    request = _request("vector")
    shard = RuntimeShard(request.resolved_scope.runtime, (uuid4(),))
    failure = RetrievalAdmissionTimeoutError(0.01)
    monkeypatch.setattr(
        vector_search,
        "search_vectors",
        lambda *args, **kwargs: vector_search.VectorSearchBatch(
            [], (vector_search.VectorShardResult(shard, [], failure),)
        ),
    )
    monkeypatch.setattr(
        lexical_search, "search_lexical", lambda *args, **kwargs: lexical_search.LexicalOutcome([], None, None)
    )
    batch = channel_collection.collect_channels(
        request,
        policy=_policy(),
        corpus_index=_corpus(monkeypatch, lambda *args, **kwargs: CorpusSearchResult([], {})),
        vector_store=object(),
    )
    assert batch.failure is failure


def test_concurrent_collection_results_keep_separate_status_and_capability_facts(monkeypatch):
    from app.rag.retrieval.corpus import CorpusSearchResult
    from app.rag.retrieval.recall import channel_collection, lexical_search

    barrier = threading.Barrier(2)
    requests = [_request(query=value) for value in ("first", "second")]

    def lexical(db, request, **kwargs):
        barrier.wait(timeout=3)
        return lexical_search.LexicalOutcome([], request.query == "first", None)

    def bm25(query, **kwargs):
        return CorpusSearchResult([{"content": query, "score": 1.0, "metadata": {}}], {"reason": query})

    monkeypatch.setattr(lexical_search, "search_lexical", lexical)
    owner = _corpus(monkeypatch, bm25)
    with ThreadPoolExecutor(max_workers=2) as executor:
        batches = list(
            executor.map(
                lambda request: channel_collection.collect_channels(
                    request, policy=_policy(), corpus_index=owner, vector_store=SimpleNamespace()
                ),
                requests,
            )
        )
    first, second = batches
    assert first.keyword.bm25.status == {"reason": "first"}
    assert second.keyword.bm25.status == {"reason": "second"}
    assert first.keyword.lexical.pg_trgm_available is True
    assert second.keyword.lexical.pg_trgm_available is False
    assert first.channels.bm25_results[0]["content"] == "first"
    assert second.channels.bm25_results[0]["content"] == "second"


def test_partial_lexical_hits_keep_the_failure_and_suppress_unneeded_fallbacks(monkeypatch):
    from app.rag.retrieval.recall import channel_collection, lexical_search

    failure = RuntimeError("trigram query failed")
    hit = {"content": "lexical kept", "score": 0.8, "metadata": {}}
    monkeypatch.setattr(
        lexical_search, "search_lexical", lambda *args, **kwargs: lexical_search.LexicalOutcome([hit], True, failure)
    )

    def unused(*args, **kwargs):
        raise AssertionError("successful lexical recall must not open a fallback backend")

    monkeypatch.setattr(channel_collection, "get_vector_store", unused)
    batch = channel_collection.collect_channels(_request(), policy=_policy(), corpus_index=_corpus(monkeypatch, unused))
    assert batch.keyword.lexical.records == [hit] and batch.keyword.lexical.failure is failure
    metrics = {}
    batch.health.publish(metrics)
    assert metrics["retrieval_degraded"] is True
    assert metrics["successful_channels"] == ["lexical_db"]
    assert batch.keyword.lexical_run_reason == "keyword_primary"


def test_exact_metadata_lookup_does_not_run_full_text_search_when_primary_has_enough_candidates(monkeypatch):
    from app.rag.retrieval.corpus import CorpusSearchResult
    from app.rag.retrieval.recall import channel_collection, lexical_search

    hits = [{"chunk_id": key, "metadata": {}} for key in ("first", "second")]
    exact_hit = {"chunk_id": "exact", "metadata": {}}
    calls = []

    def broad_search(*args, **kwargs):
        calls.append("body")
        return lexical_search.LexicalOutcome([], None)

    def exact_search(db, request, **kwargs):
        calls.append("metadata")
        return lexical_search.LexicalOutcome([exact_hit], None)

    monkeypatch.setattr(channel_collection._ChannelCollector, "_vector_search", lambda self: None)
    monkeypatch.setattr(lexical_search, "search_lexical", broad_search)
    monkeypatch.setattr(lexical_search, "search_metadata_exact", exact_search)
    request = _request("hybrid", "优抚对象医疗保障")
    request = replace(request, options=replace(request.options, top_k=8, requested_k=2))
    batch = channel_collection.collect_channels(
        request,
        policy=_policy(lexical_metadata_exact_fallback_enabled=True, metadata_exact_db_enabled=True),
        corpus_index=_corpus(monkeypatch, lambda *args, **kwargs: CorpusSearchResult(hits, {})),
    )

    assert calls == ["metadata"]
    assert batch.keyword.metadata_exact.protected_records == [exact_hit]


def test_hybrid_supplement_shares_one_deadline_across_body_and_metadata(monkeypatch):
    from app.rag.retrieval.corpus import CorpusSearchResult
    from app.rag.retrieval.recall import channel_collection, lexical_search

    now = 20.0
    deadlines = []

    def broad_search(db, request, **kwargs):
        nonlocal now
        deadlines.append(request.deadline)
        now = 20.125
        return lexical_search.LexicalOutcome([], None)

    def exact_search(db, request, **kwargs):
        deadlines.append(request.deadline)
        return lexical_search.LexicalOutcome([], None)

    monkeypatch.setattr(channel_collection, "time", SimpleNamespace(perf_counter=lambda: now))
    monkeypatch.setattr(channel_collection._ChannelCollector, "_vector_search", lambda self: None)
    monkeypatch.setattr(lexical_search, "search_lexical", broad_search)
    monkeypatch.setattr(lexical_search, "search_metadata_exact", exact_search)
    duplicate_hits = [{"chunk_id": "same", "metadata": {}}] * 2
    channel_collection.collect_channels(
        _request("hybrid", "优抚对象医疗保障"),
        policy=_policy(lexical_metadata_exact_fallback_enabled=True, metadata_exact_db_enabled=True),
        corpus_index=_corpus(monkeypatch, lambda *args, **kwargs: CorpusSearchResult(duplicate_hits, {})),
    )

    assert len(deadlines) == 2
    assert deadlines[0] == deadlines[1] > now


def test_collection_executes_with_corpus_owner_without_importing_reader() -> None:
    script = """
import importlib.abc
import sys
from uuid import uuid4
class NoReader(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'app.rag.retrieval.recall.retriever':
            raise AssertionError('Collection imports reader')
sys.meta_path.insert(0, NoReader())
from app.infrastructure.config import settings
from app.rag.retrieval.corpus import CorpusIndex
from app.rag.retrieval.recall.channel_collection import ChannelPolicy, ChannelRequest, collect_channels
from app.rag.retrieval.recall.runtime_scope import ResolvedRetrievalScope, RetrievalScope
from app.rag.retrieval.configuration.options import HybridSearchOptions
from app.services.datasets.embedding_config import DatasetEmbeddingRuntimeConfig
settings.BM25_INDEX_ENABLED = True
settings.VECTOR_BACKEND = 'milvus'
scope = RetrievalScope(uuid4(), 'actor')
class BM25Store:
    def search(self, query, **kwargs):
        assert query == 'apple' and kwargs['tenant_id'] == scope.tenant_id
        assert kwargs['top_k'] == 2
        return [{'chunk_id':'apple','content':'apple orchard','score':1.0,'metadata':{'tenant_id':str(scope.tenant_id)}}]
owner = CorpusIndex(bm25_store=BM25Store())
runtime = DatasetEmbeddingRuntimeConfig('local','test','','','space','documents',False)
resolved = ResolvedRetrievalScope(scope, (), (), runtime, None, None, None, False)
policy = ChannelPolicy(True,False,False,True,False,False)
batch = collect_channels(ChannelRequest('apple', HybridSearchOptions(top_k=1,retrieval_mode='keyword'), resolved), policy=policy, corpus_index=owner)
assert batch.channels.bm25_results[0]['content'] == 'apple orchard'
assert batch.keyword.bm25.status['reason'] == 'ok'
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


def test_complete_channel_failures_retain_original_exceptions(monkeypatch):
    from app.rag.retrieval.recall import channel_collection

    bm25_failure = RuntimeError("corpus unavailable")
    vector_failure = ConnectionError("vector unavailable")

    def bm25(*args, **kwargs):
        raise bm25_failure

    def vectors(**kwargs):
        raise vector_failure

    batch = channel_collection.collect_channels(
        _request(),
        policy=_policy(lexical_enabled=False),
        corpus_index=_corpus(monkeypatch, bm25),
        vector_store=SimpleNamespace(search=vectors),
    )
    assert batch.keyword.bm25_failure is bm25_failure
    assert batch.vector.failure is vector_failure
    metrics = {}
    batch.health.publish(metrics)
    assert metrics["successful_channels"] == []
    assert metrics["all_retrieval_channels_failed"] is True

import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4


def _fixture(monkeypatch, query="ordinary", records=None, top_k=3):
    from app.rag.retrieval.configuration.options import HybridSearchOptions
    from app.rag.retrieval.corpus import CorpusIndex, CorpusSearchResult
    from app.rag.retrieval.recall.channel_collection import (
        ChannelCollection,
        ChannelPlan,
        ChannelRequest,
        KeywordRecall,
        VectorRecall,
    )
    from app.rag.retrieval.recall.channel_health import RetrievalChannelHealth
    from app.rag.retrieval.recall.runtime_scope import ResolvedRetrievalScope, RetrievalScope
    from app.services.datasets.embedding_config import DatasetEmbeddingRuntimeConfig

    scope = RetrievalScope(uuid4(), "actor")
    runtime = DatasetEmbeddingRuntimeConfig("local", "test", "", "", "space", "documents", False)
    resolved = ResolvedRetrievalScope(scope, (), (), runtime, None, None, None, False)
    request = ChannelRequest(
        query, HybridSearchOptions(top_k=top_k, enable_weight_rerank=False, tenant_id=scope.tenant_id), resolved
    )
    collection = ChannelCollection(
        ChannelPlan(vector=True, bm25=True, lexical=False, keyword_strategy=None),
        VectorRecall(records=records or []),
        KeywordRecall(bm25=CorpusSearchResult([], {})),
        RetrievalChannelHealth(),
    )
    owner = CorpusIndex(bm25_store=object())
    monkeypatch.setattr(owner, "chunk_id_lookup", lambda scope, *, candidates: {})
    return request, collection, owner


def _record(chunk_id, content="candidate"):
    return {"chunk_id": chunk_id, "content": content, "score": 0.8, "metadata": {"document_id": "document"}}


def _policy(**changes):
    from app.rag.retrieval.ranking.candidates import (
        DedupPolicy,
        DiversityPolicy,
        FusionPolicy,
        RankingPolicy,
        RerankPolicy,
    )

    return replace(
        RankingPolicy(
            FusionPolicy("rrf", 60),
            DedupPolicy(False, 0.9, 100, 0),
            DiversityPolicy(0, 0, 0),
            RerankPolicy(False, "llm", 20),
        ),
        **changes,
    )


def test_equal_score_candidates_have_stable_order_and_owned_diagnostics(monkeypatch):
    from app.rag.retrieval.ranking import candidates as candidate_ranking

    request, collection, owner = _fixture(monkeypatch, records=[_record("second"), _record("first")])
    first = candidate_ranking.rank_candidates(request, collection, policy=_policy(), corpus_index=owner)
    second = candidate_ranking.rank_candidates(request, collection, policy=_policy(), corpus_index=owner)
    assert [item["chunk_id"] for item in first.records] == ["first", "second"]
    assert [item["chunk_id"] for item in second.records] == ["first", "second"]
    assert first.metrics["merged_pre_dedup"] == first.metrics["merged_post_dedup"] == 2
    second.metrics["merged_pre_dedup"] = 99
    assert first.metrics["merged_pre_dedup"] == 2


def test_concurrent_ranking_keeps_each_rerank_and_diversity_result(monkeypatch):
    from app.rag.retrieval.ranking import candidates as candidate_ranking
    from app.rag.retrieval.ranking.candidates import RerankPolicy

    barrier = threading.Barrier(2)

    class Reranker:
        def rerank(self, *, query, candidates, **kwargs):
            barrier.wait(timeout=3)
            return SimpleNamespace(
                ordered_ids=[item.id for item in candidates],
                score_map={},
                elapsed_sec=0.01,
                provider="test",
                model_used=query,
            )

    monkeypatch.setattr(candidate_ranking, "get_reranker", lambda provider: Reranker())
    monkeypatch.setattr(candidate_ranking.settings, "RERANK_CONDITIONAL_ENABLED", False)
    fixtures = [
        _fixture(monkeypatch, query="first", records=[_record("a"), _record("b")]),
        _fixture(monkeypatch, query="second", records=[_record("c")]),
    ]
    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(
            executor.map(
                lambda fixture: candidate_ranking.rank_candidates(
                    fixture[0],
                    fixture[1],
                    policy=_policy(rerank=RerankPolicy(True, "test", 20)),
                    corpus_index=fixture[2],
                ),
                fixtures,
            )
        )
    first, second = outcomes
    assert first.metrics["rerank"]["model_used"] == "first"
    assert second.metrics["rerank"]["model_used"] == "second"
    assert first.metrics["rerank"]["candidates_n"] == first.metrics["diversity"]["before"] == 2
    assert second.metrics["rerank"]["candidates_n"] == second.metrics["diversity"]["before"] == 1
    second.diversity["moved_in"] = 99
    assert first.diversity["moved_in"] == 0


def test_optional_reranker_failure_keeps_candidates_and_the_original_error(monkeypatch):
    from app.rag.retrieval.ranking import candidates as candidate_ranking
    from app.rag.retrieval.ranking.candidates import RerankPolicy

    failure = TimeoutError("reranker unavailable")

    class Reranker:
        def rerank(self, **kwargs):
            raise failure

    monkeypatch.setattr(candidate_ranking, "get_reranker", lambda provider: Reranker())
    monkeypatch.setattr(candidate_ranking.settings, "RERANK_CONDITIONAL_ENABLED", False)
    request, collection, owner = _fixture(monkeypatch, records=[_record("a")])
    result = candidate_ranking.rank_candidates(
        request, collection, policy=_policy(rerank=RerankPolicy(True, "test", 20)), corpus_index=owner
    )
    assert [item["chunk_id"] for item in result.records] == ["a"]
    assert result.rerank_failure is failure
    assert result.metrics["rerank"]["used"] is False
    assert result.metrics["rerank"]["error"] == "reranker unavailable"


def test_metadata_protection_is_reapplied_after_document_diversity(monkeypatch):
    from app.rag.retrieval.ranking import candidates as candidate_ranking
    from app.rag.retrieval.ranking.candidates import DedupPolicy, DiversityPolicy

    protected = _record("protected", "primary")
    request, collection, owner = _fixture(monkeypatch, records=[_record("a", "primary"), _record("b", "secondary")])
    collection.keyword.metadata_exact.protected_records.append(protected)
    collection.keyword.lexical.records.append(protected)
    result = candidate_ranking.rank_candidates(
        request,
        collection,
        policy=_policy(dedup=DedupPolicy(True, 0.9, 100, 0), diversity=DiversityPolicy(1, 0, 0)),
        corpus_index=owner,
    )
    assert "protected" in [item["chunk_id"] for item in result.records]
    assert result.metrics["metadata_exact_db"]["protected_after_diversity_added"] == 1


def test_full_candidate_operation_executes_with_corpus_owner_without_reader_imports() -> None:
    script = """
import importlib.abc
import sys
from uuid import uuid4
class NoReader(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'app.rag.retrieval.recall.retriever':
            raise AssertionError('Candidate operation imports reader')
sys.meta_path.insert(0, NoReader())
from app.infrastructure.config import settings
from app.rag.retrieval.corpus import CorpusIndex
from app.rag.retrieval.recall.candidate_retrieval import CandidateRequest, retrieve_candidates
from app.rag.retrieval.ranking.candidates import FusionPolicy, DedupPolicy, DiversityPolicy, RerankPolicy, RankingPolicy
from app.rag.retrieval.recall.channel_collection import ChannelPolicy
from app.rag.retrieval.recall.runtime_scope import ResolvedRetrievalScope, RetrievalScope
from app.rag.retrieval.configuration.options import HybridSearchOptions
from app.services.datasets.embedding_config import DatasetEmbeddingRuntimeConfig
for name in ['RETRIEVAL_CANDIDATE_CACHE_ENABLED','RETRIEVAL_CANDIDATE_SINGLEFLIGHT_ENABLED','SEMANTIC_CACHE_ENABLED']:
    setattr(settings, name, False)
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
request = CandidateRequest('apple', HybridSearchOptions(top_k=1,retrieval_mode='keyword',enable_weight_rerank=False), resolved, None)
channels = ChannelPolicy(True,False,False,True,False,False)
ranking = RankingPolicy(FusionPolicy('rrf',60),DedupPolicy(False,0.9,100,0),DiversityPolicy(0,0,0),RerankPolicy(False,'llm',20))
batch = retrieve_candidates(request, channel_policy=channels, ranking_policy=ranking, corpus_index=owner)
assert batch.failure is None and batch.candidates[0]['content'] == 'apple orchard'
assert batch.collection.keyword.bm25.status['reason'] == 'ok'
assert batch.ranking.metrics['returned_top_k'] == 1
assert batch.resolved_scope is resolved
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

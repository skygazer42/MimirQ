"""Completed operation outcomes for reader-adapter tests, without reader state mutation."""

from app.rag.retrieval.recall.candidate_retrieval import CandidateBatch, CandidateCacheOutcome, CandidateTimings
from app.rag.retrieval.recall.channel_diagnostics import empty_channel_metrics


def completed_candidate_batch(request, candidates, *, channel_metrics=None):
    metrics = empty_channel_metrics()
    if channel_metrics is not None:
        metrics.update(channel_metrics)
    cache = CandidateCacheOutcome("computed", metrics.get("cache", {}))
    metrics["cache"] = cache.metadata
    return CandidateBatch(candidates, request.resolved_scope, None, None, cache, CandidateTimings(), metrics)


def ranking_algorithms(*, fusion_budgets=None, fusion_min_scores=None, fusion_weights=None):
    from app.infrastructure.config import settings
    from app.rag.retrieval.configuration.options import HybridSearchOptions
    from app.rag.retrieval.ranking.candidates import (
        DedupPolicy,
        DiversityPolicy,
        FusionPolicy,
        RankingPolicy,
        RerankPolicy,
        _RankingRun,
    )
    from app.rag.retrieval.recall.channel_collection import ChannelRequest
    from app.rag.retrieval.recall.runtime_scope import ResolvedRetrievalScope, RetrievalScope
    from app.services.datasets.embedding_config import DatasetEmbeddingRuntimeConfig

    runtime = DatasetEmbeddingRuntimeConfig("local", "unit-test", "", "", "space", "documents", False)
    scope = ResolvedRetrievalScope(RetrievalScope(None, None), (), (), runtime, None, None, None, False)
    request = ChannelRequest("", HybridSearchOptions(), scope)
    policy = RankingPolicy(
        FusionPolicy(
            settings.RETRIEVAL_FUSION_STRATEGY,
            settings.RETRIEVAL_RRF_K,
            fusion_budgets,
            fusion_min_scores,
            fusion_weights,
        ),
        DedupPolicy(False, settings.RETRIEVAL_DEDUP_JACCARD_THRESHOLD, settings.RETRIEVAL_DEDUP_MAX_COMPARE, 0),
        DiversityPolicy(0, 0, 0),
        RerankPolicy(False, settings.RERANKER_PROVIDER, settings.RERANKER_TOP_N),
    )
    return _RankingRun(request, policy=policy)

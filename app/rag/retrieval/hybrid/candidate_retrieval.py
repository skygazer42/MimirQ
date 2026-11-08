"""Candidate request identity and the owned cache/singleflight lifecycle."""

import copy
import time
from dataclasses import dataclass
from types import TracebackType
from typing import Any, Literal, cast

from app.core.config import settings
from app.rag import retrieval_candidate_cache as candidate_cache
from app.rag.retrieval.corpus_index import CorpusIndex, CorpusScope
from app.rag.retrieval.hybrid import candidate_ranking, channel_collection
from app.rag.retrieval.hybrid.cache_scope import HybridCacheScopeDecision, prepare_hybrid_cache_scope
from app.rag.retrieval.hybrid.channel_diagnostics import empty_channel_metrics, serialize_collected_channels
from app.rag.retrieval.hybrid.channel_health import RetrievalChannelHealth
from app.rag.retrieval.hybrid.common import NON_CRITICAL_RETRIEVER_FALLBACK_LOG, _log_retriever_fallback, logger
from app.rag.retrieval.hybrid.runtime_scope import ResolvedRetrievalScope
from app.rag.retrieval.retriever_options import (
    HybridSearchOptions,
    _dataset_scoped_runtime_lookup_error,
    _metadata_filter_has_dataset_scope,
)

CacheSource = Literal["miss", "exact", "semantic", "local_singleflight", "distributed_singleflight", "computed"]


@dataclass(frozen=True)
class CandidateRequest:
    query: str
    options: HybridSearchOptions
    resolved_scope: ResolvedRetrievalScope
    behavior_hash: str | None


@dataclass(frozen=True)
class CandidateCacheOutcome:
    source: CacheSource
    metadata: dict[str, Any]


@dataclass(frozen=True)
class CandidateTimings:
    vector_ms: float = 0.0
    colbert_ms: float = 0.0
    bm25_ms: float = 0.0
    lexical_ms: float = 0.0
    fusion_ms: float = 0.0


@dataclass(frozen=True)
class CandidateBatch:
    candidates: list[dict[str, Any]]
    resolved_scope: ResolvedRetrievalScope
    collection: channel_collection.ChannelCollection | None
    ranking: candidate_ranking.RankedCandidates | None
    cache: CandidateCacheOutcome
    timings: CandidateTimings
    channel_metrics: dict[str, Any]
    failure: Exception | None = None


def retrieve_candidates(
    request: CandidateRequest,
    *,
    channel_policy: channel_collection.ChannelPolicy,
    ranking_policy: candidate_ranking.RankingPolicy,
    corpus_index: CorpusIndex,
) -> CandidateBatch:
    """Own recall through cache publication, preserving original failures and cleanup."""
    cache = CandidateCacheSession(request, corpus_index=corpus_index)
    channel_request = channel_collection.ChannelRequest(request.query, request.options, request.resolved_scope)
    metrics = empty_channel_metrics()
    collection = None
    ranking = None
    candidates = []
    failure = None
    try:
        with cache:
            cached = cache.lookup()
            if cached is not None:
                candidates = cached
            else:
                collection = channel_collection.collect_channels(
                    channel_request, policy=channel_policy, corpus_index=corpus_index
                )
                collection.health.publish(metrics)
                if collection.failure is not None:
                    raise collection.failure
                ranking = candidate_ranking.rank_candidates(
                    channel_request, collection, policy=ranking_policy, corpus_index=corpus_index
                )
                metrics = serialize_collected_channels(
                    channel_request,
                    collection,
                    policy=channel_policy,
                    fusion=ranking_policy.fusion,
                    channels=ranking.channels,
                )
                ranking_metrics = dict(ranking.metrics)
                protected = ranking_metrics.pop("metadata_exact_db", None)
                if protected is not None:
                    metrics.setdefault("metadata_exact_db", {}).update(protected)
                metrics.update(ranking_metrics)
                metrics["timing"]["fusion_ms"] = round(ranking.fusion_elapsed_ms, 2)
                candidates = ranking.records[: request.options.top_k]
                cache.publish(candidates, degraded=metrics["retrieval_degraded"])
    except Exception as exc:
        failure = exc
        if isinstance(exc, LookupError) and cache.scope_decision.scope_failure_reason is not None:
            health = RetrievalChannelHealth()
            health.failed("scope", exc)
            health.publish(metrics)
    metrics["cache"] = cache.outcome.metadata
    timings = CandidateTimings(
        vector_ms=collection.vector.elapsed_ms if collection is not None else 0.0,
        colbert_ms=collection.vector.colbert_elapsed_ms if collection is not None else 0.0,
        bm25_ms=collection.keyword.bm25_elapsed_ms if collection is not None else 0.0,
        lexical_ms=collection.keyword.lexical_elapsed_ms if collection is not None else 0.0,
        fusion_ms=ranking.fusion_elapsed_ms if ranking is not None else 0.0,
    )
    return CandidateBatch(
        candidates, request.resolved_scope, collection, ranking, cache.outcome, timings, metrics, failure
    )


def _cache_scope(request: CandidateRequest) -> HybridCacheScopeDecision:
    resolved = request.resolved_scope
    return prepare_hybrid_cache_scope(
        cache_enabled=settings.RETRIEVAL_CANDIDATE_CACHE_ENABLED,
        distributed_singleflight_enabled=settings.RETRIEVAL_CANDIDATE_SINGLEFLIGHT_ENABLED,
        semantic_cache_enabled=settings.SEMANTIC_CACHE_ENABLED,
        semantic_cache_dataset_scoped=resolved.runtime.dataset_scoped,
        tenant_id=resolved.scope.tenant_id,
        account_id=resolved.scope.account_id,
        dataset_scope_ids=resolved.dataset_scope_ids,
        document_ids=list(resolved.scope.document_ids),
        metadata_filter_dataset_scoped=_metadata_filter_has_dataset_scope(resolved.metadata_filter),
        document_scope_resolution_failed=False,
        runtime_scope_ids=resolved.runtime_dataset_ids,
        runtime_shard_count=len(resolved.runtime_shards),
        runtime_scope_missing_dataset_ids=resolved.missing_dataset_ids,
        runtime_pipeline_values=[shard.runtime.embedding_space_hash for shard in resolved.runtime_shards],
        embedding_space=resolved.runtime.embedding_space_hash,
        cache_ttl=settings.RETRIEVAL_CANDIDATE_CACHE_TTL_SEC,
        semantic_cache_ttl=settings.SEMANTIC_CACHE_TTL_SEC,
    )


class CandidateCacheSession:
    """Own admission, cache reads, result publication, and the leases of one request.

    A miss must be followed by publish before leaving the context. Cache failures
    retain the established optional-cache degradation policy; scope and wait
    failures remain explicit.
    """

    def __init__(self, request: CandidateRequest, *, corpus_index: CorpusIndex) -> None:
        self.request = request
        self._corpus_index = corpus_index
        self.scope_decision = _cache_scope(request)
        self.metadata = self.scope_decision.cache_meta
        self.key: str | None = None
        self._token: str | None = None
        self._exact_enabled = self.scope_decision.cache_eligible
        self._singleflight_enabled = self.scope_decision.distributed_singleflight_eligible
        self._semantic_enabled = self.scope_decision.semantic_cache_eligible
        self._local_leader = False
        self._lease: candidate_cache._DistributedRetrievalLease | None = None
        self._finished = False
        self._source: CacheSource = "miss"

    def __enter__(self) -> "CandidateCacheSession":
        return self

    def __exit__(
        self, exc_type: type[BaseException] | None, error: BaseException | None, traceback: TracebackType | None
    ) -> None:
        key = self.key
        try:
            if self._local_leader and key and not self._finished:
                failure = (
                    error if error is not None else RuntimeError("Candidate retrieval ended before publishing a result")
                )
                candidate_cache.reject_inflight_retrieval_candidates(key, failure)
                if error is None:
                    raise failure
        finally:
            self._release_lease()

    @property
    def outcome(self) -> CandidateCacheOutcome:
        return CandidateCacheOutcome(source=self._source, metadata=copy.deepcopy(self.metadata))

    def _release_lease(self) -> None:
        if self._lease is not None:
            lease, self._lease = self._lease, None
            candidate_cache.release_distributed_inflight_retrieval_candidates(lease)

    def _admit(self) -> None:
        if self.scope_decision.scope_failure_reason is not None:
            resolved = self.request.resolved_scope
            raise _dataset_scoped_runtime_lookup_error(
                tenant_id=resolved.scope.tenant_id,
                dataset_ids=resolved.missing_dataset_ids or resolved.runtime_dataset_ids,
                document_ids=list(resolved.scope.document_ids),
                reason="unavailable",
            )
        if not (self._exact_enabled or self._singleflight_enabled or self._semantic_enabled):
            return
        # Cache admission requires a tenant, so this scope is present on every admitted path.
        self._token = self._corpus_index.resolve_version(cast(CorpusScope, self.request.resolved_scope.corpus_scope))
        if self._token:
            return
        if self._exact_enabled:
            self.metadata["skip_reason"] = "missing_corpus_cache_token"
        if self._semantic_enabled:
            self.metadata["semantic"]["skip_reason"] = "missing_corpus_cache_token"
        self._exact_enabled = self._singleflight_enabled = self._semantic_enabled = False
        self.metadata["enabled"] = False
        self.metadata["singleflight_enabled"] = False
        self.metadata["semantic"]["enabled"] = False

    def _semantic_parameters(self) -> dict[str, Any]:
        options = self.request.options
        return {
            "tenant_id": str(self.request.resolved_scope.scope.tenant_id),
            "account_id": self.scope_decision.account_id,
            "dataset_id": self.scope_decision.dataset_id,
            "corpus_cache_token": self._token,
            "behavior_hash": self.request.behavior_hash,
            "query": self.request.query,
            "top_k": options.top_k,
            "score_threshold": options.score_threshold,
            "retrieval_mode": (options.retrieval_mode or "hybrid").lower(),
            "metadata_filter": self.request.resolved_scope.metadata_filter,
            "document_ids": self.scope_decision.document_ids,
        }

    def lookup(self) -> list[dict[str, Any]] | None:
        self._admit()
        options = self.request.options
        if self._exact_enabled or self._singleflight_enabled:
            try:
                parameters = self._semantic_parameters()
                self.key = candidate_cache.build_retrieval_candidate_cache_key(
                    **parameters,
                    pipeline_key=self.scope_decision.pipeline_key,
                )
                cached = candidate_cache.get_cached_retrieval_candidates(self.key) if self._exact_enabled else None
                if cached:
                    self._source = "exact"
                    self.metadata["hit"] = True
                    self.metadata.pop("skip_reason", None)
                    self._finished = True
                    return cached[: options.top_k]
            except Exception as exc:
                _log_retriever_fallback("_hybrid_search", exc)
                self._exact_enabled = self._singleflight_enabled = False
                self.metadata["skip_reason"] = "lookup_error"
        if self._semantic_enabled and self._token:
            try:
                from app.services import semantic_cache

                cached, metadata = semantic_cache.get_cached_semantic_payload(**self._semantic_parameters())
                self.metadata["semantic"].update(metadata)
                if cached:
                    self._source = "semantic"
                    self.metadata["semantic"]["hit"] = True
                    self.metadata["semantic"].pop("skip_reason", None)
                    self._finished = True
                    return cached[: options.top_k]
            except Exception as exc:
                _log_retriever_fallback("_hybrid_search", exc)
                self.metadata["semantic"]["skip_reason"] = "lookup_error"
        if self._singleflight_enabled and self.key:
            return self._acquire_singleflight(self.key)
        return None

    def _acquire_singleflight(self, key: str) -> list[dict[str, Any]] | None:
        try:
            self._local_leader, future = candidate_cache.acquire_inflight_retrieval_candidates(key)
            if not self._local_leader:
                started = time.perf_counter()
                try:
                    payload = candidate_cache.wait_for_inflight_retrieval_candidates(
                        key,
                        future,
                        timeout_sec=max(1.0, settings.RETRIEVAL_CANDIDATE_SINGLEFLIGHT_WAIT_TIMEOUT_SEC),
                    )
                finally:
                    self.metadata["local_singleflight_wait_ms"] = round(
                        max(0.0, (time.perf_counter() - started) * 1000.0), 1
                    )
                if isinstance(payload, list):
                    return self._follower_result(payload, distributed=False)
            self.metadata["singleflight_role"] = "leader"
            started = time.perf_counter()
            try:
                leader, payload, self._lease = (
                    candidate_cache.acquire_or_wait_for_distributed_inflight_retrieval_candidates(key)
                )
            finally:
                self.metadata["distributed_singleflight_wait_ms"] = round(
                    max(0.0, (time.perf_counter() - started) * 1000.0), 1
                )
            if leader:
                return None
            if isinstance(payload, list):
                candidate_cache.resolve_inflight_retrieval_candidates(key, payload)
                return self._follower_result(payload, distributed=True)
            self._local_leader = False
        except candidate_cache.RetrievalCandidateSingleflightTimeoutError:
            raise
        except Exception as exc:
            _log_retriever_fallback("_hybrid_search", exc)
            self._lease = None
        return None

    def _follower_result(self, payload: list[dict[str, Any]], *, distributed: bool) -> list[dict[str, Any]]:
        self._source = "distributed_singleflight" if distributed else "local_singleflight"
        self.metadata["singleflight_hit"] = True
        self.metadata["singleflight_role"] = "follower"
        if distributed:
            self.metadata["distributed_singleflight_hit"] = True
        self._finished = True
        return payload[: self.request.options.top_k]

    def publish(self, payload: list[dict[str, Any]], *, degraded: bool) -> None:
        self._source = "computed"
        if degraded:
            self.metadata["store_skip_reason"] = "retrieval_degraded"
            self.metadata["semantic"]["store_skip_reason"] = "retrieval_degraded"
        if not degraded and self._exact_enabled and self.key and payload:
            try:
                self.metadata["store_ok"] = bool(candidate_cache.set_cached_retrieval_candidates(self.key, payload))
            except Exception as exc:
                logger.debug(NON_CRITICAL_RETRIEVER_FALLBACK_LOG, exc)
        if self._local_leader and self.key:
            if degraded:
                candidate_cache.reject_inflight_retrieval_candidates(self.key, RuntimeError("retrieval degraded"))
            else:
                candidate_cache.publish_distributed_inflight_retrieval_candidates(self.key, payload)
                candidate_cache.resolve_inflight_retrieval_candidates(self.key, payload)
            self._release_lease()
        if not degraded and self._semantic_enabled and self._token and payload:
            try:
                from app.services import semantic_cache

                self.metadata["semantic"]["store_ok"] = bool(
                    semantic_cache.set_cached_semantic_payload(**self._semantic_parameters(), payload=payload)
                )
            except Exception as exc:
                logger.debug(NON_CRITICAL_RETRIEVER_FALLBACK_LOG, exc)
        self._finished = True

"""
Hybrid Retriever: Vector retrieval + BM25 + optional MMR diversity reranking.
Reference: RAG_Agent example repository. Retrieval modes and reranking strategies are configurable.
"""

import logging
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, ClassVar
from uuid import UUID

from langchain_core.callbacks import AsyncCallbackManagerForRetrieverRun, CallbackManagerForRetrieverRun
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from pydantic import ConfigDict, PrivateAttr
from sqlalchemy.orm import Session

from app.infrastructure.config import settings
from app.infrastructure.database.connection import SessionLocal
from app.rag.retrieval.cache.candidates import (
    reject_current_inflight_retrieval_candidates,
    release_current_distributed_inflight_retrieval_candidates,
)
from app.rag.retrieval.configuration.fingerprint import _build_retrieval_cache_behavior_hash
from app.rag.retrieval.configuration.options import (
    HybridSearchOptions,
    _resolve_hybrid_search_options,
    normalize_rerank_profile,
    resolve_rerank_search_k,
)
from app.rag.retrieval.corpus import get_corpus_index, is_milvus_bm25_enabled
from app.rag.retrieval.evidence.validity import requests_current_evidence
from app.rag.retrieval.planning.entities import extract_partition_keys
from app.rag.retrieval.ranking import candidates as candidate_ranking
from app.rag.retrieval.ranking.diversity import DedupDiversityMixin
from app.rag.retrieval.ranking.metadata_ordering import order_metadata_anchors
from app.rag.retrieval.ranking.policy import RetrievalPolicyMixin
from app.rag.retrieval.recall import candidate_retrieval, channel_collection
from app.rag.retrieval.recall.channel_diagnostics import empty_channel_metrics
from app.rag.retrieval.recall.common import (
    _RETRIEVAL_EXPECTED_EMBEDDING_SPACE_KEY,
    NON_CRITICAL_RETRIEVER_FALLBACK_LOG,
)
from app.rag.retrieval.recall.enrichment import CandidateEnrichmentMixin
from app.rag.retrieval.recall.runtime_scope import (
    ResolvedRetrievalScope,
    RetrievalScope,
    _metadata_filter_has_dataset_scope,
    default_embedding_runtime,
    normalize_dataset_scope_ids,
    resolve_runtime_scope,
    with_dataset_scope_filter,
)
from app.services.datasets.embedding_config import (
    DatasetEmbeddingRuntimeConfig,
)
from app.services.runtime.retrieval_limiter import run_blocking_retrieval_call
from app.types.document_metadata import metadata_text

if TYPE_CHECKING:
    from app.query.normalize import NormalizedQuery

logger = logging.getLogger("rag.retriever")


class HybridRetriever(
    DedupDiversityMixin,
    CandidateEnrichmentMixin,
    RetrievalPolicyMixin,
    BaseRetriever,
):
    """Hybrid Retriever: Vector + Keyword BM25, optional MMR reranking."""

    HybridSearchOptions: ClassVar[type[HybridSearchOptions]] = HybridSearchOptions

    k: int = 5
    score_threshold: float = settings.SIMILARITY_THRESHOLD
    alpha: float = settings.RETRIEVAL_DEFAULT_ALPHA
    retrieval_mode: str = "hybrid"  # hybrid | vector | keyword | mmr
    enable_weight_rerank: bool = True
    vector_weight: float = 0.6
    keyword_weight: float = 0.4
    mmr_lambda: float = settings.RETRIEVAL_MMR_LAMBDA
    mmr_fetch_k_multiplier: int = settings.RETRIEVAL_MMR_FETCH_K_MULTIPLIER
    enable_reranker: bool = settings.ENABLE_RERANKER
    reranker_provider: str = settings.RERANKER_PROVIDER
    reranker_top_n: int = settings.RERANKER_TOP_N
    fusion_strategy: str = settings.RETRIEVAL_FUSION_STRATEGY
    rrf_k: int = settings.RETRIEVAL_RRF_K
    # Optional: override channel fusion behavior per retriever instance (used by Evidence API / ablations).
    # Only used when fusion_strategy="budgeted_rrf".
    fusion_budgets: dict[str, int] | None = None
    fusion_min_scores: dict[str, float] | None = None
    # Only used when fusion_strategy="weighted".
    fusion_weights: dict[str, float] | None = None
    retrieval_overfetch_multiplier: int | None = None
    retrieval_overfetch_max_k: int | None = None
    dedup_enabled: bool = settings.RETRIEVAL_DEDUP_ENABLED
    dedup_jaccard_threshold: float = settings.RETRIEVAL_DEDUP_JACCARD_THRESHOLD
    dedup_max_compare: int = settings.RETRIEVAL_DEDUP_MAX_COMPARE
    max_chunks_per_doc: int = settings.RETRIEVAL_MAX_CHUNKS_PER_DOC
    max_chunks_per_record_identity: int = settings.RETRIEVAL_MAX_CHUNKS_PER_RECORD_IDENTITY
    max_chunks_per_page: int = settings.RETRIEVAL_MAX_CHUNKS_PER_PAGE
    min_distinct_docs: int = settings.RETRIEVAL_MIN_DISTINCT_DOCS
    tenant_id: UUID | None = None
    # Optional: used for candidate-level ACL trimming when retrieval is not pre-scoped
    # by document_ids. When set, results are filtered fail-closed.
    account_id: str | None = None
    # Optional: dataset scope. When set, results are restricted to documents within the dataset.
    dataset_id: UUID | None = None
    dataset_ids: list[UUID] | None = None
    document_ids: list[UUID] | None = None
    # Metadata filtering
    metadata_filter: dict[str, Any] | None = None
    entity_key: str | None = None
    partition_keys: list[str] | None = None
    entity_candidates: list[str] | None = None
    metadata_filter_enabled: bool = settings.RETRIEVAL_METADATA_FILTER_ENABLED
    retrieval_profile: str | None = None
    context_neighbor_window: int | None = None
    context_neighbor_max_added: int | None = None
    context_neighbor_score_driven: bool | None = None
    context_neighbor_high_threshold: float | None = None
    context_neighbor_mid_threshold: float | None = None
    context_neighbor_high_span: int | None = None
    context_neighbor_mid_span: int | None = None
    current_evidence_only: bool | None = None
    enable_hierarchy_recall: bool = False
    hierarchy_family_collapse: bool = settings.HIERARCHY_RECALL_FAMILY_COLLAPSE
    hierarchy_overfetch_factor: int = max(1, int(settings.HIERARCHY_RECALL_OVERFETCH_FACTOR))
    lexical_db_hybrid_fallback_only: bool | None = None
    lexical_db_hybrid_metadata_exact_fallback_enabled: bool | None = None
    metadata_exact_db_fallback_enabled: bool | None = None

    model_config = ConfigDict(arbitrary_types_allowed=True)

    # Best-effort debug metrics for the last retrieval call (per retriever instance).
    # Used by debug endpoints / observability to expose trimming/overfetch behavior.
    _last_debug_metrics: dict[str, Any] = PrivateAttr(default_factory=dict)
    # Per-query retrieval channel metrics (vector/BM25/lexical DB) for attribution/debugging.
    # Populated by `_hybrid_search` and embedded into `_last_debug_metrics` by `_get_relevant_documents`.
    _last_channel_metrics: dict[str, Any] = PrivateAttr(default_factory=dict)
    # Last BM25 readiness/lazy-build status for current query (PII-safe, no ids/query text).
    _last_bm25_status: dict[str, Any] = PrivateAttr(default_factory=dict)
    # Doc/page diversity caps (max chunks per doc/page, min distinct docs) effects for the last call.
    # PII-safe: numeric only (no ids, no query text).
    _last_diversity_caps: dict[str, Any] = PrivateAttr(default_factory=dict)
    # Cache whether pg_trgm is available for lexical DB search (per retriever instance).
    _lexical_pg_trgm_available: bool | None = PrivateAttr(default=None)

    def _open_session(self) -> Session:
        # Session factory hook for mixin methods. Resolved from this module's
        # globals at call time so tests that monkeypatch
        # ``app.rag.retrieval.recall.retriever.SessionLocal`` keep intercepting sessions opened
        # by code that lives in ``app.rag.retrieval.recall``.
        return SessionLocal()

    def _explicit_dataset_scope_ids(self) -> tuple[UUID, ...]:
        if self.dataset_id is not None:
            return (self.dataset_id,)
        return normalize_dataset_scope_ids(tuple(self.dataset_ids or ()))

    def _with_dataset_scope_filter(self, metadata_filter: dict[str, Any] | None) -> dict[str, Any] | None:
        return with_dataset_scope_filter(metadata_filter, dataset_ids=self._explicit_dataset_scope_ids())

    @staticmethod
    def _normalize_partition_keys(value: Any, *, max_items: int = 8) -> list[str]:
        out: list[str] = []
        seen: set[str] = set()

        if isinstance(value, str):
            raw_items = [value]
        elif isinstance(value, (list, tuple, set)):
            raw_items = list(value)
        else:
            raw_items = []

        for raw in raw_items:
            if raw is None:
                continue
            text = str(raw).strip()
            if not text:
                continue
            norm = text.casefold()
            if norm in seen:
                continue
            seen.add(norm)
            out.append(text)
            if len(out) >= max(0, int(max_items or 0)):
                break
        return out

    def _resolve_entity_partition_keys(
        self,
        *,
        query: str,
        entity_key: str | None = None,
        partition_keys: list[str] | None = None,
        entity_candidates: list[str] | None = None,
    ) -> list[str]:
        explicit_keys = self._normalize_partition_keys(partition_keys)
        if explicit_keys:
            return explicit_keys

        explicit_entity = str((entity_key if entity_key is not None else "")).strip()
        if explicit_entity:
            return [explicit_entity]

        candidates = entity_candidates if entity_candidates is not None else self.entity_candidates
        if not candidates:
            return []

        return extract_partition_keys(query, candidates)

    def _merge_entity_partition_metadata_filter(
        self,
        *,
        query: str,
        metadata_filter: dict[str, Any] | None,
        entity_key: str | None = None,
        partition_keys: list[str] | None = None,
        entity_candidates: list[str] | None = None,
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        keys = self._resolve_entity_partition_keys(
            query=query,
            entity_key=entity_key if entity_key is not None else self.entity_key,
            partition_keys=partition_keys if partition_keys is not None else self.partition_keys,
            entity_candidates=entity_candidates,
        )
        if not keys:
            return metadata_filter, None

        merged = dict((metadata_filter if metadata_filter is not None else {}))
        existing = merged.get("partition_keys")
        if existing is None:
            merged["partition_keys"] = {"$in": list(keys)}
        elif isinstance(existing, dict) and isinstance(existing.get("$in"), (list, tuple, set)):
            allowed = set()
            for value in existing["$in"]:
                if value is None:
                    continue
                text = str(value).strip()
                if text:
                    allowed.add(text)
            merged["partition_keys"] = {"$in": [k for k in keys if k in allowed]}
        else:
            existing_text = str(existing).strip()
            merged["partition_keys"] = {"$in": [k for k in keys if k == existing_text]}

        routing_entity_key = entity_key
        if not routing_entity_key:
            routing_entity_key = self.entity_key
        routing_entity_key = routing_entity_key.strip() if routing_entity_key is not None else None
        if not routing_entity_key:
            routing_entity_key = None
        routing_candidates = entity_candidates
        if not routing_candidates:
            routing_candidates = self.entity_candidates
        meta = {
            "entity_key": routing_entity_key,
            "partition_keys": list(keys),
            "candidates_count": len(routing_candidates) if routing_candidates else 0,
        }
        return merged, meta

    def _resolve_embedding_runtime(self, *, tenant_id: UUID | None) -> DatasetEmbeddingRuntimeConfig:
        dataset_ids = self._explicit_dataset_scope_ids()
        if tenant_id is None or not dataset_ids:
            return default_embedding_runtime()
        scope = RetrievalScope(tenant_id=tenant_id, account_id=self.account_id, dataset_ids=dataset_ids)
        db = self._open_session()
        try:
            return resolve_runtime_scope(db, scope=scope).runtime
        finally:
            try:
                db.close()
            except Exception as exc:
                logger.debug(NON_CRITICAL_RETRIEVER_FALLBACK_LOG, exc)

    def _hybrid_search(
        self,
        query: str,
        *,
        options: HybridSearchOptions | None = None,
        embedding_runtime: DatasetEmbeddingRuntimeConfig | None = None,
        **legacy_overrides: Any,
    ) -> list[dict[str, Any]]:
        return self._hybrid_search_batch(
            query,
            options=options,
            embedding_runtime=embedding_runtime,
            **legacy_overrides,
        ).candidates

    def _hybrid_search_batch(
        self,
        query: str,
        *,
        options: HybridSearchOptions | None = None,
        embedding_runtime: DatasetEmbeddingRuntimeConfig | None = None,
        **legacy_overrides: Any,
    ) -> candidate_retrieval.CandidateBatch:
        try:
            return self._hybrid_search_impl(
                query,
                options=options,
                embedding_runtime=embedding_runtime,
                **legacy_overrides,
            )
        except Exception as exc:
            release_current_distributed_inflight_retrieval_candidates()
            reject_current_inflight_retrieval_candidates(exc)
            raise

    def _hybrid_search_impl(
        self,
        query: str,
        *,
        options: HybridSearchOptions | None = None,
        embedding_runtime: DatasetEmbeddingRuntimeConfig | None = None,
        **legacy_overrides: Any,
    ) -> candidate_retrieval.CandidateBatch:
        """Resolve the request contract and delegate candidate retrieval."""
        self._last_channel_metrics = empty_channel_metrics()
        self._last_diversity_caps = {}
        search_options = _resolve_hybrid_search_options(options=options, legacy_overrides=legacy_overrides)
        resolved_scope = self._resolve_hybrid_runtime_scope(
            query=query,
            options=search_options,
            embedding_runtime=embedding_runtime,
        )
        cache_enabled = bool(
            settings.RETRIEVAL_CANDIDATE_SINGLEFLIGHT_ENABLED
            or settings.RETRIEVAL_CANDIDATE_CACHE_ENABLED
            or settings.SEMANTIC_CACHE_ENABLED
        )
        request = candidate_retrieval.CandidateRequest(
            query=query,
            options=search_options,
            resolved_scope=resolved_scope,
            behavior_hash=(
                _build_retrieval_cache_behavior_hash(retriever=self, options=search_options) if cache_enabled else None
            ),
        )
        batch = candidate_retrieval.retrieve_candidates(
            request,
            channel_policy=self._hybrid_channel_policy(),
            ranking_policy=self._hybrid_ranking_policy(),
            corpus_index=get_corpus_index(),
        )
        self._last_channel_metrics = batch.channel_metrics
        self._last_diversity_caps = batch.ranking.diversity if batch.ranking is not None else {}
        if batch.collection is not None:
            self._last_bm25_status = batch.collection.keyword.bm25.status
            self._lexical_pg_trgm_available = batch.collection.keyword.lexical.pg_trgm_available
        if batch.failure is not None:
            raise batch.failure
        return batch

    def _resolve_hybrid_runtime_scope(
        self,
        *,
        query: str,
        options: HybridSearchOptions,
        embedding_runtime: DatasetEmbeddingRuntimeConfig | None,
    ) -> ResolvedRetrievalScope:
        metadata_filter = options.metadata_filter if options.metadata_filter and self.metadata_filter_enabled else None
        if self.metadata_filter_enabled:
            metadata_filter, _entity_routing = self._merge_entity_partition_metadata_filter(
                query=query,
                metadata_filter=metadata_filter,
                entity_key=options.entity_key,
                partition_keys=options.partition_keys,
                entity_candidates=options.entity_candidates,
            )
        metadata_filter = self._with_dataset_scope_filter(metadata_filter)
        scope = RetrievalScope(
            tenant_id=options.tenant_id or self.tenant_id,
            account_id=self.account_id,
            dataset_ids=self._explicit_dataset_scope_ids(),
            document_ids=tuple(options.document_ids or ()),
            metadata_filter=metadata_filter,
        )
        db = SessionLocal()
        try:
            return resolve_runtime_scope(db, scope=scope, embedding_runtime=embedding_runtime)
        finally:
            db.close()

    def _hybrid_channel_policy(self) -> channel_collection.ChannelPolicy:
        lexical_hybrid_fallback_only = (
            bool(self.lexical_db_hybrid_fallback_only)
            if self.lexical_db_hybrid_fallback_only is not None
            else bool(settings.LEXICAL_DB_HYBRID_FALLBACK_ONLY)
        )
        lexical_metadata_exact_fallback_enabled = (
            bool(self.lexical_db_hybrid_metadata_exact_fallback_enabled)
            if self.lexical_db_hybrid_metadata_exact_fallback_enabled is not None
            else bool(settings.LEXICAL_DB_HYBRID_METADATA_EXACT_FALLBACK_ENABLED)
        )
        metadata_exact_db_enabled = (
            bool(self.metadata_exact_db_fallback_enabled)
            if self.metadata_exact_db_fallback_enabled is not None
            else bool(settings.RETRIEVAL_METADATA_EXACT_DB_FALLBACK_ENABLED)
        )
        return channel_collection.ChannelPolicy(
            bm25_enabled=is_milvus_bm25_enabled(),
            lexical_enabled=bool(settings.LEXICAL_DB_ENABLED),
            keyword_bm25_secondary_enabled=bool(settings.RETRIEVAL_KEYWORD_BM25_SECONDARY_ENABLED),
            lexical_hybrid_fallback_only=lexical_hybrid_fallback_only,
            lexical_metadata_exact_fallback_enabled=lexical_metadata_exact_fallback_enabled,
            metadata_exact_db_enabled=metadata_exact_db_enabled,
            pg_trgm_available=self._lexical_pg_trgm_available,
        )

    def _hybrid_ranking_policy(self) -> candidate_ranking.RankingPolicy:
        return candidate_ranking.RankingPolicy(
            fusion=candidate_ranking.FusionPolicy(
                strategy=self.fusion_strategy,
                rrf_k=self.rrf_k,
                budgets=self.fusion_budgets,
                min_scores=self.fusion_min_scores,
                weights=self.fusion_weights,
            ),
            dedup=candidate_ranking.DedupPolicy(
                enabled=self.dedup_enabled,
                jaccard_threshold=self.dedup_jaccard_threshold,
                max_compare=self.dedup_max_compare,
                max_chunks_per_record_identity=self.max_chunks_per_record_identity,
            ),
            diversity=candidate_ranking.DiversityPolicy(
                max_chunks_per_doc=self.max_chunks_per_doc,
                max_chunks_per_page=self.max_chunks_per_page,
                min_distinct_docs=self.min_distinct_docs,
            ),
            rerank=candidate_ranking.RerankPolicy(
                enabled=self.enable_reranker,
                provider=self.reranker_provider,
                top_n=self.reranker_top_n,
            ),
        )

    def _get_relevant_documents(
        self,
        query: str,
        *,
        run_manager: CallbackManagerForRetrieverRun,
    ) -> list[Document]:
        current_evidence_only = self.current_evidence_only
        if current_evidence_only is None:
            current_evidence_only = requests_current_evidence(query)
        valid_at = datetime.now(UTC) if current_evidence_only else None
        original_query, query, query_norm = self._normalize_retrieval_query(query)
        metadata_filter_dataset_scoped, dataset_scope_ids = self._validate_retrieval_scope_requirements()
        requested_k, search_k, fetch_k, overfetch_reasons = self._retrieval_search_budget(
            dataset_scope_ids=dataset_scope_ids,
        )
        debug = self._build_retrieval_debug_payload(
            original_query=original_query,
            normalized_query=query,
            query_norm=query_norm,
            dataset_scope_ids=dataset_scope_ids,
            metadata_filter_dataset_scoped=metadata_filter_dataset_scoped,
            requested_k=requested_k,
            search_k=search_k,
            fetch_k=fetch_k,
            overfetch_reasons=overfetch_reasons,
        )
        effective_metadata_filter = self._effective_retrieval_metadata_filter(query=query, debug=debug)
        self._record_milvus_pushdown_debug(debug)
        candidate_batch = self._invoke_hybrid_retrieval(
            query=query,
            embedding_runtime=None,
            effective_metadata_filter=effective_metadata_filter,
            requested_k=requested_k,
            search_k=search_k,
        )
        self._record_hybrid_debug_metrics(debug, candidate_batch)
        results = self._post_process_retrieval_results(
            query=query,
            results=candidate_batch.candidates,
            debug=debug,
            effective_metadata_filter=effective_metadata_filter,
            embedding_runtime=candidate_batch.resolved_scope.runtime,
            requested_k=requested_k,
            valid_at=valid_at,
        )
        docs = self._results_to_documents(results, debug=debug, requested_k=requested_k)
        self._last_debug_metrics = debug
        return docs

    def _normalize_retrieval_query(self, query: str) -> tuple[str, str, "NormalizedQuery"]:
        max_query_chars = int(settings.RETRIEVAL_QUERY_MAX_CHARS)
        if len(query) > max_query_chars:
            raise ValueError(f"retrieval query exceeds RETRIEVAL_QUERY_MAX_CHARS={max_query_chars}")
        from app.query.normalize import normalize_query

        query_norm = normalize_query(query)
        return query, query_norm.normalized_text, query_norm

    def _validate_retrieval_scope_requirements(self) -> tuple[bool, tuple[UUID, ...]]:
        metadata_filter_dataset_scoped = bool(
            self.metadata_filter_enabled and _metadata_filter_has_dataset_scope(self.metadata_filter)
        )
        dataset_scope_ids = self._explicit_dataset_scope_ids()
        if dataset_scope_ids or (self.document_ids or []) or metadata_filter_dataset_scoped:
            return metadata_filter_dataset_scoped, dataset_scope_ids
        if not settings.CHAT_ALLOW_OPEN_SCOPE:
            raise ValueError("dataset_id is required when document_ids is empty")
        return metadata_filter_dataset_scoped, dataset_scope_ids

    def _retrieval_search_budget(
        self,
        *,
        dataset_scope_ids: tuple[UUID, ...],
    ) -> tuple[int, int, int, list[str]]:
        requested_k = max(1, int(self.k or 0))
        search_k = requested_k
        if self.enable_reranker:
            search_k = resolve_rerank_search_k(
                requested_k=search_k,
                profile=str(settings.RERANK_PROFILE),
            )
        hierarchy_family_collapse_enabled = self._should_apply_hierarchy_family_collapse()
        hierarchy_overfetch_factor = max(1, int(self.hierarchy_overfetch_factor or 1))
        if hierarchy_family_collapse_enabled and hierarchy_overfetch_factor > 1:
            search_k = max(search_k, requested_k * hierarchy_overfetch_factor)
        overfetch_reasons = self._retrieval_overfetch_reasons(dataset_scope_ids=dataset_scope_ids)
        if overfetch_reasons:
            search_k = self._apply_retrieval_overfetch_bounds(requested_k=requested_k, search_k=search_k)
        fetch_k = search_k * 2
        if self.retrieval_mode.strip().lower() == "mmr":
            fetch_k = search_k * max(1, int(self.mmr_fetch_k_multiplier or 0))
        return requested_k, search_k, fetch_k, overfetch_reasons

    def _retrieval_overfetch_reasons(self, *, dataset_scope_ids: tuple[UUID, ...]) -> list[str]:
        if self.document_ids:
            return []
        reasons: list[str] = []
        metadata_filter_requested = bool(
            self.metadata_filter_enabled and isinstance(self.metadata_filter, dict) and self.metadata_filter
        )
        if not dataset_scope_ids and self.tenant_id and (self.account_id is not None and self.account_id.strip()):
            reasons.append("open_scope_acl")
        if dataset_scope_ids or (self.tenant_id and (self.account_id is not None and self.account_id.strip())):
            reasons.append("active_pipeline")
        if metadata_filter_requested:
            reasons.append("metadata_filter")
        return reasons

    def _apply_retrieval_overfetch_bounds(self, *, requested_k: int, search_k: int) -> int:
        mult_source = (
            self.retrieval_overfetch_multiplier
            if self.retrieval_overfetch_multiplier is not None
            else settings.RETRIEVAL_OVERFETCH_MULTIPLIER
        )
        mult = max(1, int(mult_source or 1))
        if mult > 1:
            search_k = max(search_k, requested_k * mult)
        cap_source = (
            self.retrieval_overfetch_max_k
            if self.retrieval_overfetch_max_k is not None
            else settings.RETRIEVAL_OVERFETCH_MAX_K
        )
        cap = int(cap_source or 0)
        if cap > 0:
            search_k = min(search_k, cap)
        return search_k

    def _build_retrieval_debug_payload(
        self,
        *,
        original_query: str,
        normalized_query: str,
        query_norm: "NormalizedQuery",
        dataset_scope_ids: tuple[UUID, ...],
        metadata_filter_dataset_scoped: bool,
        requested_k: int,
        search_k: int,
        fetch_k: int,
        overfetch_reasons: list[str],
    ) -> dict[str, Any]:
        retrieval_profile = self.retrieval_profile.strip().lower() if self.retrieval_profile is not None else None
        if not retrieval_profile:
            retrieval_profile = None
        return {
            "requested_k": requested_k,
            "search_k": search_k,
            "fetch_k": fetch_k,
            "overfetch_enabled": search_k > requested_k,
            "overfetch_reasons": overfetch_reasons,
            "retrieval_profile": retrieval_profile,
            "rerank_profile": normalize_rerank_profile(str(settings.RERANK_PROFILE)),
            "hierarchy_family_collapse_enabled": self._should_apply_hierarchy_family_collapse(),
            "hierarchy_overfetch_factor": max(1, int(self.hierarchy_overfetch_factor or 1)),
            "overfetch_multiplier": int(
                self.retrieval_overfetch_multiplier
                if self.retrieval_overfetch_multiplier is not None
                else settings.RETRIEVAL_OVERFETCH_MULTIPLIER
            ),
            "overfetch_cap_k": int(
                self.retrieval_overfetch_max_k
                if self.retrieval_overfetch_max_k is not None
                else settings.RETRIEVAL_OVERFETCH_MAX_K
            ),
            "query_normalization": {
                "original": original_query,
                "normalized": normalized_query,
                "applied_rules": list(query_norm.applied_rules),
            },
            "scope": {
                "tenant_id": str(self.tenant_id) if self.tenant_id is not None else None,
                "account_id_present": bool((self.account_id is not None and self.account_id.strip())),
                "dataset_id": str(self.dataset_id) if self.dataset_id is not None else None,
                "dataset_ids_count": len(dataset_scope_ids),
                "document_ids_count": len(self.document_ids or []),
                "kind": self._retrieval_scope_kind(
                    dataset_scope_ids=dataset_scope_ids,
                    metadata_filter_dataset_scoped=metadata_filter_dataset_scoped,
                ),
            },
        }

    def _retrieval_scope_kind(
        self,
        *,
        dataset_scope_ids: tuple[UUID, ...],
        metadata_filter_dataset_scoped: bool,
    ) -> str:
        if self.document_ids:
            return "document_ids"
        if self.dataset_id is not None:
            return "dataset_id"
        if dataset_scope_ids:
            return "dataset_ids"
        if metadata_filter_dataset_scoped:
            return "metadata_dataset_id"
        return "open"

    def _effective_retrieval_metadata_filter(self, *, query: str, debug: dict[str, Any]) -> dict[str, Any] | None:
        effective_metadata_filter = self.metadata_filter
        entity_routing_meta: dict[str, Any] | None = None
        if self.metadata_filter_enabled:
            effective_metadata_filter, entity_routing_meta = self._merge_entity_partition_metadata_filter(
                query=query,
                metadata_filter=self.metadata_filter,
                entity_key=self.entity_key,
                partition_keys=self.partition_keys,
                entity_candidates=self.entity_candidates,
            )
        effective_metadata_filter = self._with_dataset_scope_filter(effective_metadata_filter)
        if entity_routing_meta:
            debug["entity_routing"] = entity_routing_meta
        return effective_metadata_filter

    def _record_milvus_pushdown_debug(self, debug: dict[str, Any]) -> None:
        max_doc_ids = settings.MILVUS_EXPR_MAX_DOC_IDS
        debug["milvus_doc_id_pushdown_skipped"] = bool(
            settings.VECTOR_BACKEND == "milvus"
            and max_doc_ids > 0
            and self.document_ids
            and len(self.document_ids) > max_doc_ids
        )
        debug["milvus_expr_max_doc_ids"] = max_doc_ids

    def _invoke_hybrid_retrieval(
        self,
        *,
        query: str,
        embedding_runtime: DatasetEmbeddingRuntimeConfig | None,
        effective_metadata_filter: dict[str, Any] | None,
        requested_k: int,
        search_k: int,
    ) -> candidate_retrieval.CandidateBatch:
        return self._hybrid_search_batch(
            query=query,
            embedding_runtime=embedding_runtime,
            top_k=search_k,
            score_threshold=self.score_threshold,
            document_ids=self.document_ids,
            tenant_id=self.tenant_id,
            alpha=self.alpha,
            enable_weight_rerank=self.enable_weight_rerank,
            vector_weight=self.vector_weight,
            keyword_weight=self.keyword_weight,
            retrieval_mode=self.retrieval_mode,
            mmr_lambda=self.mmr_lambda,
            mmr_fetch_k_multiplier=self.mmr_fetch_k_multiplier,
            metadata_filter=effective_metadata_filter,
            entity_key=self.entity_key,
            partition_keys=self.partition_keys,
            entity_candidates=self.entity_candidates,
            requested_k=requested_k,
        )

    def _record_hybrid_debug_metrics(self, debug: dict[str, Any], batch: candidate_retrieval.CandidateBatch) -> None:
        channels = batch.channel_metrics
        debug["hybrid_results"] = len(batch.candidates)
        debug["channels"] = dict(channels)
        debug["retrieval_degraded"] = channels["retrieval_degraded"]
        debug["retrieval_degraded_reasons"] = list(channels["degraded_reasons"])
        debug["all_retrieval_channels_failed"] = channels["all_retrieval_channels_failed"]
        debug["timing"] = dict(channels["timing"])
        debug["counts"] = {key: channels["counts"][key] for key in ("vector_candidates", "bm25_candidates")}
        if batch.ranking is not None and batch.ranking.diversity:
            debug["diversity"] = dict(batch.ranking.diversity)

    def _post_process_retrieval_results(
        self,
        *,
        query: str,
        results: list[dict[str, Any]],
        debug: dict[str, Any],
        effective_metadata_filter: dict[str, Any] | None,
        embedding_runtime: DatasetEmbeddingRuntimeConfig,
        requested_k: int,
        valid_at: datetime | None,
    ) -> list[dict[str, Any]]:
        results, enrich1, enrich_count = self._enrich_retrieval_results(
            results,
            effective_metadata_filter=effective_metadata_filter,
            embedding_runtime=embedding_runtime,
            valid_at=valid_at,
        )
        debug["enrich_pass1"] = enrich1
        self._record_late_filter_collapse(debug, enrich1=enrich1, enrich_count=enrich_count)
        enriched_result_keys = {self._result_key(item) for item in results if isinstance(item, dict)}
        results = self._expand_results_with_neighbors(results)
        debug["neighbors_delta"] = len(results or []) - enrich_count
        n_neighbors = len(results or [])
        results = self._auto_merge_parent_child(results)
        debug["parent_child_merge_delta"] = len(results or []) - n_neighbors
        results, enrich2 = self._reenrich_expanded_results(
            results,
            enriched_result_keys=enriched_result_keys,
            effective_metadata_filter=effective_metadata_filter,
            embedding_runtime=embedding_runtime,
            valid_at=valid_at,
        )
        debug["enrich_pass2"] = enrich2
        results = self._apply_retrieval_post_ordering(query=query, results=results, debug=debug)
        results = self._apply_retrieval_post_policies(results=results, debug=debug, requested_k=requested_k)
        return results

    def _enrich_retrieval_results(
        self,
        results: list[dict[str, Any]],
        *,
        effective_metadata_filter: dict[str, Any] | None,
        embedding_runtime: DatasetEmbeddingRuntimeConfig,
        valid_at: datetime | None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any], int]:
        enrich_stats: dict[str, Any] = {}
        results = self._enrich_results_with_db_metadata(
            results,
            stats=enrich_stats,
            metadata_filter_override=effective_metadata_filter,
            embedding_runtime=embedding_runtime,
            valid_at=valid_at,
        )
        return results, enrich_stats, len(results)

    def _record_late_filter_collapse(
        self, debug: dict[str, Any], *, enrich1: dict[str, Any], enrich_count: int
    ) -> None:
        before = debug["hybrid_results"]
        dropped = max(0, before - enrich_count)
        debug["late_filter_collapse"] = {
            "before": before,
            "after": enrich_count,
            "dropped": dropped,
            "ratio": round(dropped / max(1, before), 6),
            "filtered_acl": enrich1.get("filtered_acl", 0),
            "filtered_dataset": enrich1.get("filtered_dataset", 0),
            "filtered_not_ready": enrich1.get("filtered_not_ready", 0),
            "filtered_pipeline_version": enrich1.get("filtered_pipeline_version", 0),
            "filtered_metadata_filter": enrich1.get("filtered_metadata_filter", 0),
            "filtered_document_validity": enrich1.get("filtered_document_validity", 0),
            "filtered_embedding_space": enrich1.get("filtered_embedding_space", 0),
            "filtered_orphaned": enrich1.get("filtered_orphaned", 0),
        }

    def _reenrich_expanded_results(
        self,
        results: list[dict[str, Any]],
        *,
        enriched_result_keys: set[str],
        effective_metadata_filter: dict[str, Any] | None,
        embedding_runtime: DatasetEmbeddingRuntimeConfig,
        valid_at: datetime | None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        enrich2: dict[str, Any] = {}
        expanded_result_keys = {self._result_key(item) for item in results if isinstance(item, dict)}
        if expanded_result_keys == enriched_result_keys:
            return results, enrich2
        results, enrich2, _count = self._enrich_retrieval_results(
            results,
            effective_metadata_filter=effective_metadata_filter,
            embedding_runtime=embedding_runtime,
            valid_at=valid_at,
        )
        return results, enrich2

    def _apply_retrieval_post_ordering(
        self,
        *,
        query: str,
        results: list[dict[str, Any]],
        debug: dict[str, Any],
    ) -> list[dict[str, Any]]:
        exact_anchor_post_stats: dict[str, Any] = {}
        results = order_metadata_anchors(
            query,
            results,
            stats=exact_anchor_post_stats,
        )
        if exact_anchor_post_stats:
            debug["metadata_exact_anchor_post"] = exact_anchor_post_stats
        return results

    def _apply_retrieval_post_policies(
        self,
        *,
        results: list[dict[str, Any]],
        debug: dict[str, Any],
        requested_k: int,
    ) -> list[dict[str, Any]]:
        gov_stats: dict[str, Any] = {}
        results = self._apply_governance_policy(results, stats=gov_stats)
        if gov_stats:
            debug["governance_policy"] = gov_stats
        collapse_stats: dict[str, Any] = {}
        results = self._collapse_results_by_family(results, stats=collapse_stats)
        if collapse_stats:
            debug["family_collapse"] = collapse_stats
        debug["final_results"] = len(results or [])
        compact_stats: dict[str, Any] = {}
        results = self._compact_high_confidence_results(results, top_k=requested_k, stats=compact_stats)
        if compact_stats:
            debug["context_compaction"] = compact_stats
        debug["stitching_enabled"] = bool(settings.RAG_CONTEXT_STITCHING_ENABLED)
        return results

    def _results_to_documents(
        self,
        results: list[dict[str, Any]],
        *,
        debug: dict[str, Any],
        requested_k: int,
    ) -> list[Document]:
        prefix = results[:requested_k]
        if prefix and settings.RAG_CONTEXT_STITCHING_ENABLED:
            try:
                prefix = self._stitch_results_for_continuity(prefix)
            except Exception as exc:
                logger.debug(NON_CRITICAL_RETRIEVER_FALLBACK_LOG, exc)
        docs = [self._document_from_result(result) for result in prefix]
        debug["final_docs"] = len(docs)
        return docs

    def _document_from_result(self, result: dict[str, Any]) -> Document:
        meta = dict(result.get("metadata") or {})
        meta.pop(_RETRIEVAL_EXPECTED_EMBEDDING_SPACE_KEY, None)
        for key in (
            "score",
            "vector_score",
            "bm25_score",
            "lexical_score",
            "field_aware_signal",
            "field_aware_boost",
            "chunk_type_signal",
            "chunk_type_boost",
            "keyword_score",
            "exact_phrase_score",
            "exact_phrase_boost",
            "exact_phrase_matches",
            "metadata_exact_match_score",
            "metadata_exact_match_primary_score",
            "metadata_exact_match_boost",
            "metadata_exact_match_field",
            "metadata_exact_match_value",
            "metadata_exact_match_fields",
            "metadata_exact_match_values",
            "metadata_exact_match_promoted_score",
            "rerank_score_final",
            "rerank_score",
            "retrieval_score",
            "reranker_provider",
            "rerank_elapsed_sec",
            "rerank_model_used",
        ):
            if key in result:
                meta[key] = result[key]
        return Document(page_content=result["content"], metadata=meta, id=result.get("chunk_id"))

    def _apply_governance_policy(
        self,
        results: list[dict[str, Any]],
        *,
        stats: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """
        Apply lifecycle preferences over already-enriched final candidates.

        Policies:
        - prefer_authority: small additive boost based on documents.authority_level (0-100)
        - prefer_latest: small additive boost for recently updated documents
        - filter_superseded: drop older documents when their replacement is also a candidate

        The document enrichment pass supplies every feature used here, so this stage performs
        no database, retrieval, or model calls.
        """
        if stats is not None:
            stats.clear()

        if not results:
            return results

        prefer_authority = settings.RETRIEVAL_GOVERNANCE_PREFER_AUTHORITY
        prefer_latest = settings.RETRIEVAL_GOVERNANCE_PREFER_LATEST
        filter_superseded = settings.RETRIEVAL_GOVERNANCE_FILTER_SUPERSEDED

        enabled = bool(prefer_authority or prefer_latest or filter_superseded)
        if stats is not None:
            stats["enabled"] = enabled
            stats["prefer_authority"] = bool(prefer_authority)
            stats["prefer_latest"] = bool(prefer_latest)
            stats["filter_superseded"] = bool(filter_superseded)
            stats["feature_source"] = "candidate_metadata"
            stats["db_roundtrips"] = 0

        if not enabled:
            return results

        if stats is not None:
            stats["input_results"] = len(results)

        doc_features, unpublished_doc_ids, superseded_doc_ids = self._collect_governance_features(
            results,
            filter_superseded=filter_superseded,
        )

        if stats is not None:
            stats["candidate_docs"] = len(doc_features)

        out, filtered_unpublished, filtered_superseded = self._filter_governance_results(
            results,
            unpublished_doc_ids=unpublished_doc_ids,
            superseded_doc_ids=superseded_doc_ids,
            filter_superseded=filter_superseded,
        )
        out, reordered, avg_boost, max_boost = self._reorder_governance_results(
            out,
            doc_features=doc_features,
            prefer_authority=prefer_authority,
            prefer_latest=prefer_latest,
        )

        if stats is not None:
            stats["filtered_unpublished"] = int(filtered_unpublished)
            stats["filtered_superseded"] = int(filtered_superseded)
            stats["output_results"] = len(out)
            stats["reordered"] = bool(reordered)
            # Keep numeric-only summary for downstream debugging/observability.
            stats["avg_boost"] = round(float(avg_boost), 6)
            stats["max_boost"] = round(float(max_boost), 6)

        return out

    def _collect_governance_features(
        self,
        results: list[dict[str, Any]],
        *,
        filter_superseded: bool,
    ) -> tuple[dict[str, dict[str, Any]], set[str], set[str]]:
        doc_features: dict[str, dict[str, Any]] = {}
        superseded_doc_ids: set[str] = set()
        unpublished_doc_ids: set[str] = set()
        for result in results:
            doc_id = self._get_doc_id(result)
            if not doc_id:
                continue
            features = self._governance_features_for_result(result)
            doc_features[doc_id] = features
            if features["publication_status"] != "published":
                unpublished_doc_ids.add(doc_id)
            supersedes_id = metadata_text(features, "supersedes_document_id")
            if filter_superseded and features["publication_status"] == "published" and supersedes_id:
                superseded_doc_ids.add(supersedes_id)
        return doc_features, unpublished_doc_ids, superseded_doc_ids

    @staticmethod
    def _governance_features_for_result(result: dict[str, Any]) -> dict[str, Any]:
        meta = result.get("metadata") or {}
        try:
            authority = int(meta.get("_governance_authority_level", meta.get("authority_level", 0)) or 0)
        except (TypeError, ValueError):
            authority = 0
        try:
            updated_ts = float(meta.get("_governance_updated_ts", meta.get("updated_ts")))
        except (TypeError, ValueError):
            updated_ts = None
        publication_status = (
            str(meta.get("_governance_publication_status", meta.get("publication_status", "published")) or "published")
            .strip()
            .lower()
        )
        return {
            "authority_level": max(0, min(100, authority)),
            "updated_ts": updated_ts,
            "publication_status": publication_status,
            "supersedes_document_id": metadata_text(meta, "_governance_supersedes_document_id")
            if "_governance_supersedes_document_id" in meta
            else metadata_text(meta, "supersedes_document_id"),
        }

    def _filter_governance_results(
        self,
        results: list[dict[str, Any]],
        *,
        unpublished_doc_ids: set[str],
        superseded_doc_ids: set[str],
        filter_superseded: bool,
    ) -> tuple[list[dict[str, Any]], int, int]:
        out = list(results)
        filtered_unpublished = 0
        if unpublished_doc_ids:
            before = len(out)
            out = [result for result in out if self._get_doc_id(result) not in unpublished_doc_ids]
            filtered_unpublished = max(0, before - len(out))
        filtered_superseded = 0
        if filter_superseded and superseded_doc_ids:
            before = len(out)
            out = [result for result in out if self._get_doc_id(result) not in superseded_doc_ids]
            filtered_superseded = max(0, before - len(out))
        return out, filtered_unpublished, filtered_superseded

    def _reorder_governance_results(
        self,
        results: list[dict[str, Any]],
        *,
        doc_features: dict[str, dict[str, Any]],
        prefer_authority: bool,
        prefer_latest: bool,
    ) -> tuple[list[dict[str, Any]], bool, float, float]:
        if not (prefer_authority or prefer_latest) or not results:
            return results, False, 0.0, 0.0
        scored, boosts = self._governance_scored_rows(
            results,
            doc_features=doc_features,
            prefer_authority=prefer_authority,
            prefer_latest=prefer_latest,
        )
        ordered = [result for _score, _index, result in sorted(scored, key=lambda item: (-item[0], item[1]))]
        average_boost = sum(boosts) / len(boosts) if boosts else 0.0
        return ordered, ordered != results, average_boost, max(boosts, default=0.0)

    def _governance_scored_rows(
        self,
        results: list[dict[str, Any]],
        *,
        doc_features: dict[str, dict[str, Any]],
        prefer_authority: bool,
        prefer_latest: bool,
    ) -> tuple[list[tuple[float, int, dict[str, Any]]], list[float]]:
        auth_boost_max = float(settings.RETRIEVAL_GOVERNANCE_AUTHORITY_BOOST_MAX)
        latest_boost_max = float(settings.RETRIEVAL_GOVERNANCE_LATEST_BOOST_MAX)
        window_days = max(1, int(settings.RETRIEVAL_GOVERNANCE_LATEST_WINDOW_DAYS))
        now_ts = time.time()
        boosts: list[float] = []
        scored: list[tuple[float, int, dict[str, Any]]] = []
        for index, result in enumerate(results):
            base_score = self._governance_base_score(result)
            doc_id = self._get_doc_id(result)
            features = doc_features.get(doc_id, {})
            boost = self._governance_score_boost(
                features,
                prefer_authority=prefer_authority,
                prefer_latest=prefer_latest,
                auth_boost_max=auth_boost_max,
                latest_boost_max=latest_boost_max,
                window_days=window_days,
                now_ts=now_ts,
            )
            boosts.append(boost)
            scored.append((base_score + boost, index, result))
        return scored, boosts

    @staticmethod
    def _governance_base_score(result: dict[str, Any]) -> float:
        score = result.get("score")
        if score is None:
            score = result.get("retrieval_score", 0.0)
        try:
            return float(score)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _governance_score_boost(
        features: dict[str, Any],
        *,
        prefer_authority: bool,
        prefer_latest: bool,
        auth_boost_max: float,
        latest_boost_max: float,
        window_days: int,
        now_ts: float,
    ) -> float:
        boost = 0.0
        if prefer_authority and auth_boost_max > 0.0:
            authority = features.get("authority_level", 0)
            boost += (authority / 100.0) * auth_boost_max
        updated_ts = features.get("updated_ts")
        if prefer_latest and latest_boost_max > 0.0 and updated_ts is not None and updated_ts > 0:
            age_days = max(0.0, (now_ts - updated_ts) / 86400.0)
            recency = max(0.0, 1.0 - age_days / window_days)
            boost += recency * latest_boost_max
        return boost

    async def _aget_relevant_documents(
        self,
        query: str,
        *,
        run_manager: AsyncCallbackManagerForRetrieverRun,
    ) -> list[Document]:
        return await run_blocking_retrieval_call(
            self._get_relevant_documents,
            query,
            run_manager=CallbackManagerForRetrieverRun.get_noop_manager(),
        )


# Global instance
hybrid_retriever = HybridRetriever()

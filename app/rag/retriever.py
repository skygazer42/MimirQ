"""
Hybrid Retriever: Vector retrieval + BM25 + optional MMR diversity reranking.
Reference: RAG_Agent example repository. Retrieval modes and reranking strategies are configurable.
"""

import heapq
import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, replace
from functools import lru_cache
from typing import Any, ClassVar, cast
from uuid import UUID

from langchain_community.retrievers.bm25 import BM25Retriever
from langchain_core.callbacks import AsyncCallbackManagerForRetrieverRun, CallbackManagerForRetrieverRun
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from pydantic import ConfigDict, Field, PrivateAttr
from sqlalchemy.orm import Session

from app.config.rerank_profile import resolve_rerank_search_k
from app.core.config import settings
from app.core.database import SessionLocal
from app.core.stream_events import emit_stream_event
from app.models.dataset import Dataset as DBDataset
from app.models.document import Document as DBDocument
from app.rag.core.hashing import stable_json_hash
from app.rag.core.logging import get_logger
from app.rag.embedding.utils import current_embedding_space_hash
from app.rag.reranker.factory import get_reranker
from app.rag.reranker.types import RerankCandidate
from app.rag.retrieval.hybrid.bm25_index import Bm25IndexMixin
from app.rag.retrieval.hybrid.cache_scope import prepare_hybrid_cache_scope
from app.rag.retrieval.hybrid.channel_diagnostics import update_hybrid_channel_diagnostics
from app.rag.retrieval.hybrid.channel_health import RetrievalChannelHealth
from app.rag.retrieval.hybrid.channel_results import prepare_hybrid_channel_results
from app.rag.retrieval.hybrid.colbert_index import ColbertIndexMixin
from app.rag.retrieval.hybrid.common import (
    _PIPELINE_PLUGIN_METADATA_KEYS,
    _PLATFORM_METADATA_VIEW_KEYS,
    _RETRIEVAL_DISPLAY_CONTENT_KEY,
    _RETRIEVAL_EXPECTED_EMBEDDING_SPACE_KEY,
    LEXICAL_DB_SEARCH_FAILED_LOG,
    NON_CRITICAL_RETRIEVER_FALLBACK_LOG,
    _apply_exact_content_bonus_to_result,
    _apply_metadata_exact_anchor_to_result,
    _float_or_default,
    _log_retriever_fallback,
    _query_looks_like_cjk_metadata_anchor,
    _results_contain_metadata_exact_anchor,
)
from app.rag.retrieval.hybrid.dedup import DedupDiversityMixin
from app.rag.retrieval.hybrid.fusion import FusionMixin
from app.rag.retrieval.hybrid.lexical import LexicalDBMixin
from app.rag.retrieval.hybrid.post_process import PostProcessMixin
from app.rag.retrieval.hybrid.sparse_index import SparseIndexMixin
from app.rag.retrieval.hybrid.text_preparation import (
    augment_retrieval_corpus_text,
    normalize_document_questions,
    prepare_retrieval_document,
    question_channel_overlap_score,
    rerank_text_from_result,
)
from app.rag.retrieval.planner import compact_high_confidence_items, retrieval_policy_response_compaction
from app.rag.retrieval.plugin_policy import (
    evaluate_records_retrieval_policy,
)
from app.rag.retrieval.sparse import SparseVector
from app.rag.retrieval_candidate_cache import (
    RetrievalCandidateSingleflightTimeoutError,
    acquire_inflight_retrieval_candidates,
    acquire_or_wait_for_distributed_inflight_retrieval_candidates,
    build_retrieval_candidate_cache_key,
    get_cached_retrieval_candidates,
    publish_distributed_inflight_retrieval_candidates,
    reject_current_inflight_retrieval_candidates,
    release_current_distributed_inflight_retrieval_candidates,
    release_distributed_inflight_retrieval_candidates,
    resolve_inflight_retrieval_candidates,
    set_cached_retrieval_candidates,
    wait_for_inflight_retrieval_candidates,
)
from app.services.corpus_cache_tokens import resolve_corpus_cache_token
from app.services.dataset_embedding_config import (
    DatasetEmbeddingRuntimeConfig,
    create_embeddings_for_runtime,
    resolve_dataset_embedding_runtime,
)
from app.services.rag_runtime_limiter import (
    RetrievalAdmissionTimeoutError,
    run_blocking_retrieval_call,
    run_with_retrieval_backend_budget_sync,
)
from app.storage.vector.factory import get_vector_store
from app.storage.vector.milvus import get_milvus_adapter, resolve_collection_name

logger = get_logger("rag.retriever")


def _dataset_scoped_runtime_lookup_error(
    *,
    tenant_id: UUID | None,
    dataset_ids: tuple[UUID, ...] = (),
    document_ids: list[UUID] | None = None,
    reason: str = "unavailable",
) -> LookupError:
    detail = reason.strip() or "unavailable"
    return LookupError(
        "dataset-scoped embedding runtime "
        f"{detail} (tenant_id={tenant_id}, dataset_ids={len(dataset_ids)}, document_ids={len(document_ids or [])})"
    )


_CORPUS_TOKEN_LOCAL_CACHE_TTL_SEC = 1.0
_CORPUS_TOKEN_LOCAL_CACHE_MAX_ENTRIES = 128


@dataclass(frozen=True)
class HybridSearchOptions:
    top_k: int = 5
    score_threshold: float = 0.7
    document_ids: list[UUID] | None = None
    tenant_id: UUID | None = None
    alpha: float = settings.RETRIEVAL_DEFAULT_ALPHA
    enable_weight_rerank: bool = True
    vector_weight: float = 0.6
    keyword_weight: float = 0.4
    retrieval_mode: str = "hybrid"
    mmr_lambda: float = 0.7
    mmr_fetch_k_multiplier: int = 4
    metadata_filter: dict[str, Any] | None = None
    entity_key: str | None = None
    partition_keys: list[str] | None = None
    entity_candidates: list[str] | None = None
    requested_k: int | None = None


def _resolve_hybrid_search_options(
    *,
    options: HybridSearchOptions | None,
    legacy_overrides: dict[str, Any],
) -> HybridSearchOptions:
    if options is None:
        return HybridSearchOptions(**legacy_overrides)
    if not legacy_overrides:
        return options
    return cast(HybridSearchOptions, replace(options, **legacy_overrides))


def _build_retrieval_cache_behavior_hash(
    *,
    retriever: "HybridRetriever",
    options: HybridSearchOptions,
) -> str:
    option_values = asdict(options)
    if options.document_ids:
        option_values["document_ids"] = sorted({str(document_id) for document_id in options.document_ids})
    prefixes = ("BM25_", "COLBERT_", "COLPALI_", "LEXICAL_", "RERANK", "RETRIEVAL_", "SPARSE_")
    runtime = {
        key: value
        for key, value in settings.model_dump(mode="json").items()
        if key.startswith(prefixes) or key == "VECTOR_BACKEND"
    }
    return stable_json_hash(
        {"options": option_values, "retriever": retriever.model_dump(mode="json"), "runtime": runtime},
        length=24,
    )


def _is_dataset_scope_condition(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, dict):
        if "$eq" in value:
            return bool(str(value.get("$eq") or "").strip())
        if "$in" in value:
            items = value.get("$in")
            return isinstance(items, list | tuple | set) and any(str(item or "").strip() for item in items)
        return False
    if isinstance(value, list | tuple | set):
        return any(str(item or "").strip() for item in value)
    return bool(str(value or "").strip())


def _metadata_filter_has_dataset_scope(metadata_filter: dict[str, Any] | None) -> bool:
    if not isinstance(metadata_filter, dict) or not metadata_filter:
        return False
    if _is_dataset_scope_condition(metadata_filter.get("dataset_id")):
        return True

    and_parts = metadata_filter.get("$and")
    if isinstance(and_parts, list):
        return any(
            _metadata_filter_has_dataset_scope(part)
            for part in and_parts
            if isinstance(part, dict)
        )

    or_parts = metadata_filter.get("$or")
    if isinstance(or_parts, list) and or_parts:
        scoped_parts = [
            _metadata_filter_has_dataset_scope(part)
            for part in or_parts
            if isinstance(part, dict)
        ]
        return bool(scoped_parts) and all(scoped_parts)

    return False


class HybridRetriever(
    Bm25IndexMixin,
    DedupDiversityMixin,
    FusionMixin,
    LexicalDBMixin,
    PostProcessMixin,
    SparseIndexMixin,
    ColbertIndexMixin,
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
    mmr_fetch_k_multiplier: int = getattr(settings, "RETRIEVAL_MMR_FETCH_K_MULTIPLIER", 4)
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
    # Optional: when None, follow settings.SPARSE_RETRIEVAL_ENABLED dynamically (useful for tests / hot reload).
    # When set, acts as an explicit per-retriever override.
    sparse_enabled: bool | None = None
    sparse_provider: str = Field(default_factory=lambda: settings.SPARSE_RETRIEVAL_PROVIDER)
    dedup_enabled: bool = settings.RETRIEVAL_DEDUP_ENABLED
    dedup_jaccard_threshold: float = settings.RETRIEVAL_DEDUP_JACCARD_THRESHOLD
    dedup_max_compare: int = settings.RETRIEVAL_DEDUP_MAX_COMPARE
    max_chunks_per_doc: int = settings.RETRIEVAL_MAX_CHUNKS_PER_DOC
    max_chunks_per_record_identity: int = getattr(settings, "RETRIEVAL_MAX_CHUNKS_PER_RECORD_IDENTITY", 2)
    max_chunks_per_page: int = getattr(settings, "RETRIEVAL_MAX_CHUNKS_PER_PAGE", 0)
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
    metadata_filter_enabled: bool = getattr(settings, "RETRIEVAL_METADATA_FILTER_ENABLED", True)
    retrieval_profile: str | None = None
    context_neighbor_window: int | None = None
    context_neighbor_max_added: int | None = None
    context_neighbor_score_driven: bool | None = None
    context_neighbor_high_threshold: float | None = None
    context_neighbor_mid_threshold: float | None = None
    context_neighbor_high_span: int | None = None
    context_neighbor_mid_span: int | None = None
    enable_hierarchy_recall: bool = False
    hierarchy_family_collapse: bool = getattr(settings, "HIERARCHY_RECALL_FAMILY_COLLAPSE", True)
    hierarchy_overfetch_factor: int = max(1, int(getattr(settings, "HIERARCHY_RECALL_OVERFETCH_FACTOR", 4) or 4))
    lexical_db_hybrid_fallback_only: bool | None = None
    lexical_db_hybrid_metadata_exact_fallback_enabled: bool | None = None
    metadata_exact_db_fallback_enabled: bool | None = None

    model_config = ConfigDict(arbitrary_types_allowed=True)

    _bm25_retrievers: dict[str, BM25Retriever] = PrivateAttr(default_factory=dict)
    _bm25_docs: dict[str, list[Document]] = PrivateAttr(default_factory=dict)
    _bm25_doc_ids: dict[str, set[str]] = PrivateAttr(default_factory=dict)
    _chunk_id_lookup: dict[str, dict[str, str]] = PrivateAttr(default_factory=dict)
    _bm25_deferred_scopes: set[str] = PrivateAttr(default_factory=set)
    _bm25_build_locks: dict[str, threading.Lock] = PrivateAttr(default_factory=dict)
    # LRU order for per-tenant BM25 caches (prevents unbounded growth in multi-tenant deployments).
    _bm25_cache_order: "OrderedDict[str, None]" = PrivateAttr(default_factory=OrderedDict)
    _bm25_cache_lock: threading.Lock = PrivateAttr(default_factory=threading.RLock)
    # Cache versions per BM25 scope key (used to invalidate dataset-scoped indices after ingest).
    _bm25_cache_versions: dict[str, str] = PrivateAttr(default_factory=dict)
    _corpus_token_cache: "OrderedDict[tuple[str, str, tuple[str, ...], tuple[str, ...]], tuple[float, str]]" = PrivateAttr(
        default_factory=OrderedDict
    )
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
    # Optional sparse retrieval channel caches (per scope key).
    _sparse_doc_vectors: dict[str, dict[str, SparseVector]] = PrivateAttr(default_factory=dict)
    _sparse_build_locks: dict[str, threading.Lock] = PrivateAttr(default_factory=dict)
    # Last sparse provider status for current query (PII-safe, low-cardinality).
    _last_sparse_provider_status: dict[str, Any] = PrivateAttr(default_factory=dict)
    # Optional ColBERT-style ANN retrieval caches (per scope key).
    # These are used only when settings.COLBERT_RETRIEVAL_ENABLED=true.
    _colbert_index_cache: dict[str, Any] = PrivateAttr(default_factory=dict)
    _colbert_build_locks: dict[str, threading.Lock] = PrivateAttr(default_factory=dict)

    def _open_session(self) -> Session:
        # Session factory hook for mixin methods. Resolved from this module's
        # globals at call time so tests that monkeypatch
        # ``app.rag.retriever.SessionLocal`` keep intercepting sessions opened
        # by code that lives in ``app.rag.retrieval.hybrid``.
        return SessionLocal()

    def _effective_sparse_enabled(self) -> bool:
        if self.sparse_enabled is not None:
            return bool(self.sparse_enabled)
        return bool(getattr(settings, "SPARSE_RETRIEVAL_ENABLED", False))

    def _resolve_sparse_provider_status(self, *, sparse_enabled: bool) -> dict[str, Any]:
        from app.rag.retrieval.sparse import resolve_sparse_provider_capability

        return resolve_sparse_provider_capability(
            requested_provider=str(self.sparse_provider or ""),
            sparse_enabled=bool(sparse_enabled),
            splade_model_name=str(getattr(settings, "SPARSE_SPLADE_MODEL_NAME", "") or ""),
            default_provider="deterministic",
        )

    def _tenant_key(self, tenant_id: UUID | None) -> str:
        return str(tenant_id or settings.DEFAULT_TENANT_ID)

    @staticmethod
    def _resolve_tenant_uuid(tenant_id: UUID | None) -> UUID | None:
        if tenant_id is not None:
            return tenant_id
        try:
            return UUID(str(getattr(settings, "DEFAULT_TENANT_ID", "") or ""))
        except (TypeError, ValueError, AttributeError):
            return None

    def _explicit_dataset_scope_ids(self) -> tuple[UUID, ...]:
        if self.dataset_id is not None:
            return (self.dataset_id,)
        return self._normalize_dataset_scope_ids(self.dataset_ids)

    def _dataset_scope_ids(self, document_ids: list[UUID] | None) -> tuple[UUID, ...]:
        return () if document_ids else self._explicit_dataset_scope_ids()

    @classmethod
    def _normalize_dataset_scope_ids(
        cls,
        dataset_scope_ids: list[UUID] | tuple[UUID, ...] | None,
    ) -> tuple[UUID, ...]:
        return tuple(sorted(cls._coerce_dataset_scope_values(dataset_scope_ids), key=str))

    def _with_dataset_scope_filter(
        self,
        metadata_filter: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        dataset_ids = self._explicit_dataset_scope_ids()
        if not dataset_ids:
            return metadata_filter
        scoped_filter = dict(metadata_filter or {})
        scoped_filter.setdefault("dataset_id", self._dataset_scope_filter_value(dataset_ids))
        return scoped_filter

    @staticmethod
    def _dataset_scope_filter_value(dataset_ids: tuple[UUID, ...]) -> str | dict[str, list[str]]:
        if len(dataset_ids) == 1:
            return str(dataset_ids[0])
        return {"$in": [str(dataset_id) for dataset_id in dataset_ids]}

    @staticmethod
    def _build_vector_filter(
        metadata_filter: dict[str, Any] | None,
        *,
        embedding_space: str,
        dataset_ids: tuple[UUID, ...] | None = None,
    ) -> dict[str, Any] | None:
        if not metadata_filter and not embedding_space and not dataset_ids:
            return None

        vector_allowed = {
            "tenant_id",
            "dataset_id",
            "document_id",
            "embedding_space_hash",
            "chunk_id",
            "chunk_index",
            "pipeline_hash",
            "doc_pipeline_key",
            "source",
            "file_type",
            "img_id",
            "image_id",
            "image_url",
            "page_number",
            "partition_keys",
        }
        vf: dict[str, Any] = {}
        for k, v in (metadata_filter or {}).items():
            if not isinstance(k, str):
                continue
            if "." in k:
                continue
            if k == "page":
                vf["page_number"] = v
                continue
            if k == "img_url":
                vf["image_url"] = v
                continue
            if k in vector_allowed:
                vf[k] = v

        if dataset_ids:
            vf["dataset_id"] = HybridRetriever._dataset_scope_filter_value(dataset_ids)
        if embedding_space:
            vf["embedding_space_hash"] = {"$in": [embedding_space, ""]}
        return vf or None

    @staticmethod
    def _tag_vector_hits_with_expected_space(
        hits: list[dict[str, Any]],
        *,
        expected_space: str,
    ) -> list[dict[str, Any]]:
        if not expected_space:
            return hits
        for hit in hits:
            meta = dict(hit.get("metadata") or {})
            meta[_RETRIEVAL_EXPECTED_EMBEDDING_SPACE_KEY] = expected_space
            hit["metadata"] = meta
        return hits

    def _search_vector_runtime_shards(
        self,
        *,
        query: str,
        top_k: int,
        score_threshold: float,
        document_ids: list[UUID] | None,
        tenant_id: UUID | None,
        metadata_filter: dict[str, Any] | None,
        runtime_shards: list[tuple[DatasetEmbeddingRuntimeConfig, tuple[UUID, ...]]],
        vector_store: Any,
    ) -> tuple[list[dict[str, Any]], list[Exception]]:
        def _search_shard_impl(
            shard: tuple[DatasetEmbeddingRuntimeConfig, tuple[UUID, ...]],
        ) -> tuple[list[dict[str, Any]], Exception | None]:
            shard_runtime, shard_dataset_ids = shard
            try:
                shard_filter = self._build_vector_filter(
                    metadata_filter,
                    embedding_space=str(shard_runtime.embedding_space_hash or "").strip(),
                    dataset_ids=shard_dataset_ids,
                )
                if shard_runtime.dataset_scoped:
                    hits = self._search_dataset_scoped_vectors(
                        query=query,
                        top_k=top_k,
                        score_threshold=score_threshold,
                        document_ids=document_ids,
                        tenant_id=tenant_id,
                        metadata_filter=shard_filter,
                        embedding_runtime=shard_runtime,
                    )
                else:
                    hits = vector_store.search(
                        query=query,
                        top_k=top_k,
                        score_threshold=score_threshold,
                        document_ids=document_ids,
                        tenant_id=tenant_id,
                        metadata_filter=shard_filter,
                    )
                return (
                    self._tag_vector_hits_with_expected_space(
                        hits, expected_space=str(shard_runtime.embedding_space_hash or "").strip()
                    ),
                    None,
                )
            except Exception as exc:
                logger.warning(
                    "Vector search shard failed for collection %s: %s",
                    shard_runtime.collection_name,
                    exc,
                )
                return [], exc

        def search_shard(
            shard: tuple[DatasetEmbeddingRuntimeConfig, tuple[UUID, ...]],
        ) -> tuple[list[dict[str, Any]], Exception | None]:
            try:
                return run_with_retrieval_backend_budget_sync(_search_shard_impl, shard)
            except Exception as exc:
                shard_runtime, _shard_dataset_ids = shard
                logger.warning(
                    "Vector search shard admission failed for collection %s: %s",
                    shard_runtime.collection_name,
                    exc,
                )
                return [], exc

        max_workers = min(
            len(runtime_shards),
            max(1, int(getattr(settings, "RAG_VECTOR_SHARD_MAX_CONCURRENCY", 4) or 1)),
        )
        if max_workers <= 1:
            outcomes = [search_shard(shard) for shard in runtime_shards]
        else:
            with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="rag-vector-shard") as executor:
                outcomes = list(executor.map(search_shard, runtime_shards))

        shard_results = [hit for hits, _failure in outcomes for hit in hits]
        failures = [failure for _hits, failure in outcomes if failure is not None]
        return (self._top_scored_results(shard_results, top_k), failures)

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
            text = str(raw or "").strip()
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

        explicit_entity = str(entity_key or "").strip()
        if explicit_entity:
            return [explicit_entity]

        candidates = entity_candidates if entity_candidates is not None else self.entity_candidates
        if not candidates:
            return []

        try:
            from app.rag.utils.entity_matcher import extract_partition_keys

            return extract_partition_keys(query, candidates)
        except Exception as exc:
            _log_retriever_fallback('_resolve_entity_partition_keys', exc)
            return []

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

        merged = dict(metadata_filter or {})
        existing = merged.get("partition_keys")
        if existing is None:
            merged["partition_keys"] = {"$in": list(keys)}
        elif isinstance(existing, dict) and isinstance(existing.get("$in"), (list, tuple, set)):
            allowed = {str(v or "").strip() for v in existing.get("$in") or [] if str(v or "").strip()}
            merged["partition_keys"] = {"$in": [k for k in keys if k in allowed]}
        else:
            existing_text = str(existing or "").strip()
            merged["partition_keys"] = {"$in": [k for k in keys if k == existing_text]}

        meta = {
            "entity_key": (str(entity_key or self.entity_key or "").strip() or None),
            "partition_keys": list(keys),
            "candidates_count": int(len(entity_candidates or self.entity_candidates or [])),
        }
        return merged, meta

    @staticmethod
    def _result_content_from_doc(doc: Document) -> str:
        meta = doc.metadata or {}
        preserved = meta.get(_RETRIEVAL_DISPLAY_CONTENT_KEY)
        if isinstance(preserved, str) and preserved:
            return preserved
        return str(doc.page_content or "")

    @staticmethod
    def _normalize_document_questions(value: Any, *, max_items: int = 5) -> list[str]:
        return normalize_document_questions(value, max_items=max_items)

    @staticmethod
    def _rerank_text_from_result(result: dict[str, Any]) -> str:
        return rerank_text_from_result(result)

    def _augment_retrieval_corpus_text(self, *, content: str, metadata: dict[str, Any]) -> tuple[str, bool]:
        return augment_retrieval_corpus_text(content=content, metadata=metadata)

    def _prepare_retrieval_document(self, doc: Document) -> Document:
        return prepare_retrieval_document(doc, log_fallback=_log_retriever_fallback)

    def _question_channel_overlap_score(
        self,
        *,
        query_tokens: list[str],
        metadata: dict[str, Any],
    ) -> float:
        return question_channel_overlap_score(
            query_tokens=query_tokens,
            metadata=metadata,
            tokenize=self._bm25_tokenize,
        )

    def _resolve_embedding_runtime(self, *, tenant_id: UUID | None) -> DatasetEmbeddingRuntimeConfig:
        dataset_ids = self._explicit_dataset_scope_ids()
        if tenant_id is not None and dataset_ids:
            shards = self._resolve_dataset_runtime_shards(tenant_id=tenant_id, dataset_ids=dataset_ids)
            if len(shards) == 1:
                return shards[0][0]
            if len(shards) > 1:
                runtime = resolve_dataset_embedding_runtime(None)
                return cast(
                    DatasetEmbeddingRuntimeConfig,
                    replace(runtime, embedding_space_hash=current_embedding_space_hash()),
                )
        if len(dataset_ids) != 1 or tenant_id is None:
            runtime = resolve_dataset_embedding_runtime(None)
            return cast(
                DatasetEmbeddingRuntimeConfig,
                replace(runtime, embedding_space_hash=current_embedding_space_hash()),
            )
        dataset_id = dataset_ids[0]

        db = SessionLocal()
        try:
            row = (
                db.query(DBDataset.dataset_metadata)
                .filter(DBDataset.tenant_id == tenant_id, DBDataset.id == dataset_id)
                .first()
            )
            if row is None:
                raise _dataset_scoped_runtime_lookup_error(
                    tenant_id=tenant_id,
                    dataset_ids=(dataset_id,),
                    reason="unavailable",
                )
            meta = row[0] if row else None
            if meta is not None and not isinstance(meta, dict):
                raise _dataset_scoped_runtime_lookup_error(
                    tenant_id=tenant_id,
                    dataset_ids=(dataset_id,),
                    reason="invalid",
                )
            runtime = resolve_dataset_embedding_runtime(dict(meta or {}))
            if runtime.dataset_scoped:
                return runtime
            return cast(
                DatasetEmbeddingRuntimeConfig,
                replace(runtime, embedding_space_hash=current_embedding_space_hash()),
            )
        except ValueError:
            raise
        except Exception as exc:
            if isinstance(exc, LookupError):
                raise
            _log_retriever_fallback('_resolve_embedding_runtime', exc)
            raise _dataset_scoped_runtime_lookup_error(
                tenant_id=tenant_id,
                dataset_ids=(dataset_id,),
                reason="unavailable",
            ) from exc
        finally:
            try:
                db.close()
            except Exception as exc:
                logger.debug(NON_CRITICAL_RETRIEVER_FALLBACK_LOG, exc)

    def _resolve_dataset_runtime_shards(
        self,
        *,
        tenant_id: UUID | None,
        dataset_ids: tuple[UUID, ...] | None = None,
    ) -> list[tuple[DatasetEmbeddingRuntimeConfig, tuple[UUID, ...]]]:
        scope_dataset_ids = self._normalize_dataset_scope_ids(dataset_ids or self._explicit_dataset_scope_ids())
        if tenant_id is None or not scope_dataset_ids:
            return []

        current_space = current_embedding_space_hash()
        db = SessionLocal()
        try:
            rows = (
                db.query(DBDataset.id, DBDataset.dataset_metadata)
                .filter(DBDataset.tenant_id == tenant_id, DBDataset.id.in_(scope_dataset_ids))
                .all()
            )
            metadata_by_id: dict[str, dict[str, Any]] = {}
            for dataset_id, meta in rows:
                if meta is not None and not isinstance(meta, dict):
                    raise _dataset_scoped_runtime_lookup_error(
                        tenant_id=tenant_id,
                        dataset_ids=(dataset_id,),
                        reason="invalid",
                    )
                metadata_by_id[str(dataset_id)] = dict(meta or {})
            missing_dataset_ids = tuple(dataset_id for dataset_id in scope_dataset_ids if str(dataset_id) not in metadata_by_id)
            if missing_dataset_ids:
                raise _dataset_scoped_runtime_lookup_error(
                    tenant_id=tenant_id,
                    dataset_ids=missing_dataset_ids,
                    reason="unavailable",
                )
            grouped: "OrderedDict[DatasetEmbeddingRuntimeConfig, list[UUID]]" = OrderedDict()
            for dataset_id in scope_dataset_ids:
                metadata = metadata_by_id.get(str(dataset_id))
                runtime = resolve_dataset_embedding_runtime(metadata)
                if not runtime.dataset_scoped:
                    runtime = cast(
                        DatasetEmbeddingRuntimeConfig,
                        replace(runtime, embedding_space_hash=current_space),
                    )
                grouped.setdefault(runtime, []).append(dataset_id)
            return [(runtime, tuple(group_ids)) for runtime, group_ids in grouped.items()]
        except ValueError:
            raise
        except Exception as exc:
            if isinstance(exc, LookupError):
                raise
            _log_retriever_fallback('_resolve_dataset_runtime_shards', exc)
            raise _dataset_scoped_runtime_lookup_error(
                tenant_id=tenant_id,
                dataset_ids=scope_dataset_ids,
                reason="unavailable",
            ) from exc
        finally:
            try:
                db.close()
            except Exception as exc:
                logger.debug(NON_CRITICAL_RETRIEVER_FALLBACK_LOG, exc)

    def _resolve_document_dataset_scope(
        self,
        *,
        tenant_id: UUID | None,
        document_ids: list[UUID],
    ) -> tuple[tuple[UUID, ...], bool] | None:
        """Resolve document scope to dataset IDs and whether it includes legacy unscoped documents."""
        requested = {str(document_id): document_id for document_id in document_ids if document_id is not None}
        if tenant_id is None or not requested:
            return None

        db = SessionLocal()
        try:
            rows = (
                db.query(DBDocument.id, DBDocument.dataset_id)
                .filter(DBDocument.tenant_id == tenant_id, DBDocument.id.in_(tuple(requested.values())))
                .all()
            )
            if {str(document_id) for document_id, _dataset_id in rows} != set(requested):
                return None
            return (
                self._normalize_dataset_scope_ids(
                    [dataset_id for _document_id, dataset_id in rows if dataset_id is not None]
                ),
                any(dataset_id is None for _document_id, dataset_id in rows),
            )
        except Exception as exc:
            _log_retriever_fallback("_resolve_document_dataset_scope", exc)
            return None
        finally:
            try:
                db.close()
            except Exception as exc:
                logger.debug(NON_CRITICAL_RETRIEVER_FALLBACK_LOG, exc)

    def _search_dataset_scoped_vectors(
        self,
        *,
        query: str,
        top_k: int,
        score_threshold: float,
        document_ids: list[UUID] | None,
        tenant_id: UUID | None,
        metadata_filter: dict[str, Any] | None,
        embedding_runtime: DatasetEmbeddingRuntimeConfig,
    ) -> list[dict[str, Any]]:
        embeddings = create_embeddings_for_runtime(embedding_runtime)
        query_vector = embeddings.embed_query(query)
        scoped_filter = dict(metadata_filter or {})
        if tenant_id is not None:
            scoped_filter.setdefault("tenant_id", str(tenant_id))
        if document_ids:
            scoped_filter["document_id"] = {"$in": [str(doc_id) for doc_id in document_ids]}
        adapter = get_milvus_adapter(resolve_collection_name(embedding_runtime.collection_name))
        native_hybrid_meta: dict[str, Any] = {
            "enabled": bool(getattr(settings, "MILVUS_NATIVE_HYBRID", False)),
            "used": False,
            "fallback_reason": None,
        }
        results: list[dict[str, Any]] = []
        can_try_native_hybrid = bool(
            native_hybrid_meta["enabled"]
            and str(getattr(settings, "VECTOR_BACKEND", "") or "").strip().lower() == "milvus"
            and self._effective_sparse_enabled()
        )
        if can_try_native_hybrid:
            try:
                from app.rag.retrieval.sparse import get_sparse_encoder, parse_synonyms

                sparse_status = self._resolve_sparse_provider_status(sparse_enabled=True)
                sparse_provider = (
                    str(sparse_status.get("effective_provider") or self.sparse_provider or "deterministic").strip().lower()
                    or "deterministic"
                )
                synonyms = parse_synonyms(str(getattr(settings, "SPARSE_RETRIEVAL_SYNONYMS", "") or ""))
                encoder = get_sparse_encoder(
                    provider=sparse_provider,
                    synonyms=synonyms,
                    synonyms_raw=str(getattr(settings, "SPARSE_RETRIEVAL_SYNONYMS", "") or ""),
                    model_name=str(getattr(settings, "SPARSE_SPLADE_MODEL_NAME", "") or ""),
                    device=str(getattr(settings, "SPARSE_SPLADE_DEVICE", "cpu") or "cpu"),
                    batch_size=int(getattr(settings, "SPARSE_SPLADE_BATCH_SIZE", 8) or 8),
                    max_length=int(getattr(settings, "SPARSE_SPLADE_MAX_LENGTH", 256) or 256),
                    top_k=int(getattr(settings, "SPARSE_SPLADE_TOP_K", 128) or 128),
                    min_weight=float(getattr(settings, "SPARSE_SPLADE_MIN_WEIGHT", 0.0) or 0.0),
                )
                sparse_query_vector = self._sparse_query_vector(encoder, query)
                if not getattr(sparse_query_vector, "weights", None):
                    native_hybrid_meta["fallback_reason"] = "sparse_query_empty"
                else:
                    results = adapter.search_native_hybrid(
                        query_vector=query_vector,
                        sparse_query_vector=sparse_query_vector,
                        top_k=max(1, top_k * 2),
                        metadata_filter=scoped_filter or None,
                    )
                    native_hybrid_meta["used"] = True
                    native_hybrid_meta["provider"] = sparse_provider
            except NotImplementedError:
                native_hybrid_meta["fallback_reason"] = "unsupported"
            except Exception as exc:
                _log_retriever_fallback("_search_dataset_scoped_vectors", exc)
                native_hybrid_meta["fallback_reason"] = f"error:{exc.__class__.__name__}"
        if not results:
            results = adapter.search(
                query_vector=query_vector,
                top_k=max(1, top_k * 2),
                metadata_filter=scoped_filter or None,
            )
            if can_try_native_hybrid and native_hybrid_meta.get("fallback_reason") is None:
                native_hybrid_meta["fallback_reason"] = "empty_result_fallback"
        if isinstance(self._last_channel_metrics, dict):
            self._last_channel_metrics["milvus_native_hybrid"] = native_hybrid_meta
        filtered = [r for r in results if float(r.get("score") or 0.0) >= float(score_threshold or 0.0)]
        return filtered[:top_k]

    def _resolve_candidate_cache_corpus_token(
        self,
        *,
        tenant_id: UUID | None,
        document_ids: list[UUID] | None,
        dataset_ids: list[UUID] | tuple[UUID, ...] | None = None,
    ) -> str | None:
        tenant_uuid = tenant_id or self.tenant_id
        if tenant_uuid is None:
            return None

        scope_dataset_ids = self._normalize_dataset_scope_ids(
            dataset_ids if dataset_ids is not None else self._explicit_dataset_scope_ids()
        )
        dataset_id = scope_dataset_ids[0] if len(scope_dataset_ids) == 1 else None
        multi_dataset_scope = scope_dataset_ids if len(scope_dataset_ids) > 1 else ()
        normalized_document_ids = list(dict.fromkeys(document_ids or []))
        document_scope = tuple(sorted(str(document_id) for document_id in normalized_document_ids))
        scope_key = (
            str(tenant_uuid),
            str(dataset_id or ""),
            tuple(str(dataset_scope_id) for dataset_scope_id in multi_dataset_scope),
            document_scope,
        )
        now = time.monotonic()
        with self._bm25_cache_lock:
            cached = self._corpus_token_cache.get(scope_key)
            if cached is not None and now - cached[0] <= _CORPUS_TOKEN_LOCAL_CACHE_TTL_SEC:
                self._corpus_token_cache.move_to_end(scope_key)
                return cached[1]
            self._corpus_token_cache.pop(scope_key, None)

        db = SessionLocal()
        try:
            token = resolve_corpus_cache_token(
                db,
                tenant_id=tenant_uuid,
                dataset_id=dataset_id,
                dataset_ids=multi_dataset_scope,
                document_ids=normalized_document_ids,
            )
            if token:
                with self._bm25_cache_lock:
                    self._corpus_token_cache[scope_key] = (time.monotonic(), token)
                    self._corpus_token_cache.move_to_end(scope_key)
                    while len(self._corpus_token_cache) > _CORPUS_TOKEN_LOCAL_CACHE_MAX_ENTRIES:
                        self._corpus_token_cache.popitem(last=False)
            return token
        except Exception as exc:
            _log_retriever_fallback('_resolve_candidate_cache_corpus_token', exc)
            return None
        finally:
            try:
                db.close()
            except Exception as exc:
                logger.debug(NON_CRITICAL_RETRIEVER_FALLBACK_LOG, exc)

    def _clear_candidate_corpus_token_cache(self, tenant_id: UUID | None) -> None:
        tenant_key = self._tenant_key(tenant_id)
        with self._bm25_cache_lock:
            for scope_key in [key for key in self._corpus_token_cache if key[0] == tenant_key]:
                self._corpus_token_cache.pop(scope_key, None)

    def _search_colpali_retriever(
        self,
        query: str,
        top_k: int = 10,
        document_ids: list[UUID] | None = None,
        tenant_id: UUID | None = None,
        metadata_filter: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """
        Minimal ColPali retriever scaffold.

        Today this reuses the BM25 corpus and narrows it to visual-document parser outputs
        (`visual_parser=colpali` / `content_type=visual_document` / image-like docs). This keeps
        the path deterministic and dependency-light until a dedicated page-embedding index lands.
        """
        visual_filter: dict[str, Any] = {
            "$or": [
                {"visual_parser": "colpali"},
                {"content_type": "visual_document"},
                {"doc_type_kwd": "image"},
            ]
        }
        combined_filter: dict[str, Any] | None = visual_filter
        if isinstance(metadata_filter, dict) and metadata_filter:
            combined_filter = {"$and": [dict(metadata_filter), visual_filter]}

        rows = self._search_bm25(
            query=query,
            top_k=top_k,
            document_ids=document_ids,
            tenant_id=tenant_id,
            metadata_filter=combined_filter,
        )

        out: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row or {})
            score = float(item.get("score", 0.0) or 0.0)
            meta = dict(item.get("metadata") or {})
            meta.setdefault("visual_parser", "colpali")
            meta["colpali_score"] = float(score)
            item["metadata"] = meta
            item["colpali_score"] = float(score)
            # Piggyback on lexical score so existing fusion logic can merge the channel.
            item["lexical_score"] = float(score)
            item["hit_type"] = "colpali_retriever"
            out.append(item)
        return out

    def _channel_metric_box(self, channel: str) -> dict[str, Any] | None:
        try:
            if not isinstance(self._last_channel_metrics, dict):
                return None
            box = self._last_channel_metrics.get(channel)
            if not isinstance(box, dict):
                box = {}
                self._last_channel_metrics[channel] = box
            return box
        except Exception as exc:
            logger.debug(NON_CRITICAL_RETRIEVER_FALLBACK_LOG, exc)
            return None

    def _update_channel_metric(self, channel: str, values: dict[str, Any]) -> None:
        box = self._channel_metric_box(channel)
        if box is not None:
            box.update(values)

    @staticmethod
    def _result_allowed_by_scope(
        *,
        metadata: dict[str, Any],
        allowed_ids: set[str] | None,
        metadata_filter: dict[str, Any] | None,
        metadata_filter_enabled: bool,
        matcher: Any,
    ) -> bool:
        if allowed_ids and str(metadata.get("document_id")) not in allowed_ids:
            return False
        return not (metadata_filter and metadata_filter_enabled and not matcher(metadata, metadata_filter))

    def _top_scored_results(self, results: list[dict[str, Any]], top_k: int) -> list[dict[str, Any]]:
        if not results:
            return []
        return heapq.nsmallest(
            max(0, int(top_k or 0)),
            results,
            key=lambda item: (
                -_float_or_default(item.get("score"), 0.0),
                self._result_key(item),
            ),
        )

    def _hybrid_search(
        self,
        query: str,
        *,
        options: HybridSearchOptions | None = None,
        embedding_runtime: DatasetEmbeddingRuntimeConfig | None = None,
        **legacy_overrides: Any,
    ) -> list[dict[str, Any]]:
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
    ) -> list[dict[str, Any]]:
        """Hybrid search: vector retrieval + BM25, optional reranking."""
        search_options = _resolve_hybrid_search_options(options=options, legacy_overrides=legacy_overrides)
        top_k = search_options.top_k
        score_threshold = search_options.score_threshold
        document_ids = search_options.document_ids
        tenant_id = search_options.tenant_id
        alpha = search_options.alpha
        enable_weight_rerank = search_options.enable_weight_rerank
        vector_weight = search_options.vector_weight
        keyword_weight = search_options.keyword_weight
        retrieval_mode = search_options.retrieval_mode
        mmr_lambda = search_options.mmr_lambda
        mmr_fetch_k_multiplier = search_options.mmr_fetch_k_multiplier
        cache_enabled = bool(
            getattr(settings, "RETRIEVAL_CANDIDATE_SINGLEFLIGHT_ENABLED", True)
            or getattr(settings, "RETRIEVAL_CANDIDATE_CACHE_ENABLED", False)
            or getattr(settings, "SEMANTIC_CACHE_ENABLED", False)
        )
        behavior_hash = (
            _build_retrieval_cache_behavior_hash(retriever=self, options=search_options)
            if cache_enabled
            else None
        )
        metadata_filter = search_options.metadata_filter
        entity_key = search_options.entity_key
        partition_keys = search_options.partition_keys
        entity_candidates = search_options.entity_candidates
        requested_k = search_options.requested_k

        retrieval_mode = (retrieval_mode or "hybrid").lower()

        # Best-effort per-query debug metrics (low overhead, no external deps).
        # `_get_relevant_documents` will embed these into `_last_debug_metrics`.
        channel_metrics: dict[str, Any] = {
            "timing": {"vector_ms": 0.0, "colbert_ms": 0.0, "bm25_ms": 0.0, "lexical_ms": 0.0, "fusion_ms": 0.0},
            "counts": {
                "vector_candidates": 0,
                "colbert_candidates": 0,
                "colpali_candidates": 0,
                "bm25_candidates": 0,
                "lexical_candidates": 0,
                "sparse_candidates": 0,
            },
            "retrieval_degraded": False,
            "degraded_reasons": [],
            "all_retrieval_channels_failed": False,
        }
        self._last_channel_metrics = channel_metrics
        channel_health = RetrievalChannelHealth()
        # Reset per-call diversity caps meta to avoid stale fields on cache-hit/early-return paths.
        self._last_diversity_caps = {}

        vector_elapsed_ms = 0.0
        colbert_elapsed_ms = 0.0
        bm25_elapsed_ms = 0.0
        lexical_elapsed_ms = 0.0
        colbert_used = False
        colbert_candidates = 0
        metadata_exact_protected_results: list[dict[str, Any]] = []
        colpali_results: list[dict[str, Any]] = []
        want_colpali = False
        colpali_reason = "disabled"
        tenant_uuid = tenant_id or self.tenant_id
        # Metadata filter strategy:
        # - BM25 sees Postgres chunk metadata (rich JSON) -> can apply most filters early.
        # - Milvus (document collection) stores a small fixed metadata schema -> only pass supported keys early
        #   to avoid false negatives when users filter on richer DB-only metadata.
        full_metadata_filter = metadata_filter if (metadata_filter and self.metadata_filter_enabled) else None
        if self.metadata_filter_enabled:
            full_metadata_filter, _entity_routing_meta = self._merge_entity_partition_metadata_filter(
                query=query,
                metadata_filter=full_metadata_filter,
                entity_key=entity_key,
                partition_keys=partition_keys,
                entity_candidates=entity_candidates,
            )
        # Dataset scope is a first-class retrieval boundary. Push it down via metadata_filter so:
        # - vector backends can apply it in their scalar expr/where clauses (when supported)
        # - BM25 can filter early and avoid "top_k filled by other datasets" trimming losses
        full_metadata_filter = self._with_dataset_scope_filter(full_metadata_filter)
        dataset_scope_ids = self._explicit_dataset_scope_ids()
        runtime_scope_ids = dataset_scope_ids
        document_scope_resolution_failed = False
        has_unscoped_document_runtime = False
        if not runtime_scope_ids:
            if document_ids:
                document_scope = self._resolve_document_dataset_scope(
                    tenant_id=tenant_uuid,
                    document_ids=document_ids,
                )
                if document_scope is None:
                    document_scope_resolution_failed = True
                else:
                    runtime_scope_ids, has_unscoped_document_runtime = document_scope
            else:
                runtime_scope_ids = self._normalize_dataset_scope_ids(
                    self._collect_lexical_dataset_scope(full_metadata_filter),
                )
        runtime_shards = (
            self._resolve_dataset_runtime_shards(tenant_id=tenant_uuid, dataset_ids=runtime_scope_ids)
            if runtime_scope_ids
            else []
        )
        if has_unscoped_document_runtime:
            default_runtime = self._resolve_embedding_runtime(tenant_id=None)
            runtime_shards_by_runtime = OrderedDict(runtime_shards)
            runtime_shards_by_runtime[default_runtime] = ()
            runtime_shards = list(runtime_shards_by_runtime.items())
        runtime_shard_dataset_ids = {
            dataset_id
            for _runtime, shard_dataset_ids in runtime_shards
            for dataset_id in shard_dataset_ids
        }
        runtime_scope_missing_dataset_ids = tuple(
            dataset_id for dataset_id in runtime_scope_ids if dataset_id not in runtime_shard_dataset_ids
        )
        embedding_runtime = embedding_runtime or self._resolve_embedding_runtime(tenant_id=tenant_uuid)
        if len(runtime_shards) == 1:
            embedding_runtime = runtime_shards[0][0]
        embedding_space = str(embedding_runtime.embedding_space_hash or "").strip()
        bm25_filter: dict[str, Any] | None = None
        vector_filter: dict[str, Any] | None = None
        if full_metadata_filter and isinstance(full_metadata_filter, dict):
            bm25_filter = {
                k: v
                for k, v in full_metadata_filter.items()
                if isinstance(k, str) and not str(k).startswith("document_user.")
            }
            vector_filter = self._build_vector_filter(
                bm25_filter,
                embedding_space=embedding_space,
            )

        if bool(getattr(settings, "COLPALI_RETRIEVAL_ENABLED", False)):
            try:
                from app.rag.policy.modality_router import classify_query_modality  # noqa: WPS433

                modality, _reasons = classify_query_modality(query)
                if str(modality or "").strip().lower() == "image":
                    want_colpali = True
                    colpali_reason = "image_query"
            except Exception as exc:
                _log_retriever_fallback('_hybrid_search', exc)
                colpali_reason = "router_exception"
        else:
            colpali_reason = "COLPALI_RETRIEVAL_ENABLED=false"

        lexical_db_enabled = bool(getattr(settings, "LEXICAL_DB_ENABLED", True))
        bm25_index_enabled = bool(getattr(settings, "BM25_INDEX_ENABLED", True))
        keyword_bm25_secondary_enabled = bool(
            getattr(settings, "RETRIEVAL_KEYWORD_BM25_SECONDARY_ENABLED", False)
        )

        want_vector = retrieval_mode in ("hybrid", "vector", "mmr")
        want_bm25 = retrieval_mode in ("hybrid", "keyword", "mmr")
        # Persistent lexical DB search is an additional sparse channel that does not depend on the in-memory BM25 flag.
        want_lexical = retrieval_mode in ("hybrid", "keyword", "mmr") and lexical_db_enabled
        # Optional sparse retrieval (SPLADE-style scaffolding) is an additional sparse channel.
        want_sparse = retrieval_mode in ("hybrid", "keyword", "mmr") and self._effective_sparse_enabled()
        keyword_strategy: dict[str, Any] | None = None
        if retrieval_mode == "keyword":
            if lexical_db_enabled:
                want_bm25 = keyword_bm25_secondary_enabled
                keyword_strategy = {
                    "primary": "lexical_db",
                    "secondary": "bm25" if keyword_bm25_secondary_enabled else None,
                    "bm25_secondary_enabled": bool(keyword_bm25_secondary_enabled),
                    "lexical_db_enabled": True,
                }
            else:
                want_bm25 = True
                keyword_strategy = {
                    "primary": "bm25",
                    "secondary": None,
                    "bm25_secondary_enabled": False,
                    "lexical_db_enabled": False,
                    "fallback_reason": "lexical_db_disabled",
                }
        if want_bm25 and not bm25_index_enabled:
            # Enforce the global flag even if a BM25 cache exists.
            #
            # Note: do not force-enable vector here. Lexical DB retrieval is an additional sparse channel,
            # and keyword-mode already has an explicit fallback to vector when both sparse channels return empty.
            want_bm25 = False
            if keyword_strategy is not None:
                keyword_strategy["bm25_index_enabled"] = False
        elif keyword_strategy is not None:
            keyword_strategy["bm25_index_enabled"] = bool(bm25_index_enabled)

        # Optional caches (best-effort):
        # - Retrieval candidate cache: exact match (Redis)
        # - Semantic cache: ANN match (Milvus) + payload (Redis)
        cache_key: str | None = None
        cached = None
        cache_hit = False
        semantic_cache_hit = False
        semantic_cached = None
        corpus_cache_token: str | None = None
        metadata_filter_dataset_scoped = bool(
            self.metadata_filter_enabled
            and _metadata_filter_has_dataset_scope(full_metadata_filter if isinstance(full_metadata_filter, dict) else None)
        )
        cache_scope = prepare_hybrid_cache_scope(
            cache_enabled=bool(getattr(settings, "RETRIEVAL_CANDIDATE_CACHE_ENABLED", False)),
            distributed_singleflight_enabled=bool(
                getattr(settings, "RETRIEVAL_CANDIDATE_SINGLEFLIGHT_ENABLED", True)
            ),
            semantic_cache_enabled=bool(getattr(settings, "SEMANTIC_CACHE_ENABLED", False)),
            semantic_cache_dataset_scoped=bool(embedding_runtime.dataset_scoped),
            tenant_id=tenant_uuid,
            account_id=self.account_id,
            dataset_scope_ids=dataset_scope_ids,
            document_ids=document_ids,
            metadata_filter_dataset_scoped=metadata_filter_dataset_scoped,
            document_scope_resolution_failed=document_scope_resolution_failed,
            runtime_scope_ids=runtime_scope_ids,
            runtime_shard_count=len(runtime_shards),
            runtime_scope_missing_dataset_ids=runtime_scope_missing_dataset_ids,
            runtime_pipeline_values=[
                str(runtime.embedding_space_hash or "").strip()
                for runtime, _shard_dataset_ids in runtime_shards
            ],
            embedding_space=embedding_space or None,
            cache_ttl=int(getattr(settings, "RETRIEVAL_CANDIDATE_CACHE_TTL_SEC", 0) or 0),
            semantic_cache_ttl=int(getattr(settings, "SEMANTIC_CACHE_TTL_SEC", 0) or 0),
        )
        account_id0 = cache_scope.account_id
        dataset_id0 = cache_scope.dataset_id
        pipeline_key = cache_scope.pipeline_key
        doc_ids = cache_scope.document_ids
        cache_eligible = cache_scope.cache_eligible
        distributed_singleflight_eligible = cache_scope.distributed_singleflight_eligible
        semantic_cache_eligible = cache_scope.semantic_cache_eligible
        cache_meta = cache_scope.cache_meta
        if isinstance(self._last_channel_metrics, dict):
            self._last_channel_metrics["cache"] = cache_meta

        if cache_scope.scope_failure_reason == "missing_document_runtime":
            exc = _dataset_scoped_runtime_lookup_error(
                tenant_id=tenant_uuid,
                document_ids=document_ids,
                reason="unavailable",
            )
            channel_health.failed("scope", exc)
            channel_health.publish(channel_metrics)
            raise exc

        if cache_scope.scope_failure_reason == "missing_dataset_runtime":
            exc = _dataset_scoped_runtime_lookup_error(
                tenant_id=tenant_uuid,
                dataset_ids=runtime_scope_missing_dataset_ids or runtime_scope_ids,
                document_ids=document_ids,
                reason="unavailable",
            )
            channel_health.failed("scope", exc)
            channel_health.publish(channel_metrics)
            raise exc

        if cache_eligible or distributed_singleflight_eligible or semantic_cache_eligible:
            try:
                corpus_cache_token = self._resolve_candidate_cache_corpus_token(
                    tenant_id=tenant_uuid,
                    document_ids=document_ids,
                    dataset_ids=runtime_scope_ids,
                )
            except Exception as exc:
                _log_retriever_fallback('_hybrid_search', exc)
                corpus_cache_token = None

            if not corpus_cache_token:
                if cache_eligible:
                    cache_eligible = False
                    cache_meta["skip_reason"] = "missing_corpus_cache_token"
                if distributed_singleflight_eligible:
                    distributed_singleflight_eligible = False
                if semantic_cache_eligible:
                    semantic_cache_eligible = False
                    cache_meta["semantic"]["skip_reason"] = "missing_corpus_cache_token"
        cache_meta["enabled"] = bool(cache_eligible)
        cache_meta["singleflight_enabled"] = bool(distributed_singleflight_eligible)
        cache_meta["semantic"]["enabled"] = bool(semantic_cache_eligible)

        if cache_eligible or distributed_singleflight_eligible:
            try:
                cache_key = build_retrieval_candidate_cache_key(
                    tenant_id=str(tenant_uuid),
                    account_id=account_id0,
                    dataset_id=dataset_id0,
                    pipeline_key=pipeline_key,
                    corpus_cache_token=corpus_cache_token,
                    behavior_hash=behavior_hash,
                    query=query,
                    top_k=int(top_k or 0),
                    score_threshold=float(score_threshold or 0.0),
                    retrieval_mode=retrieval_mode,
                    metadata_filter=full_metadata_filter if isinstance(full_metadata_filter, dict) else None,
                    document_ids=doc_ids,
                )
                cached = get_cached_retrieval_candidates(cache_key) if (cache_eligible and cache_key) else None
            except Exception as exc:
                _log_retriever_fallback('_hybrid_search', exc)
                cached = None
                cache_eligible = False
                distributed_singleflight_eligible = False
                cache_meta["skip_reason"] = "lookup_error"

        if cached:
            cache_hit = True
            try:
                if isinstance(self._last_channel_metrics, dict):
                    self._last_channel_metrics.setdefault("cache", {})  # type: ignore[call-arg]
                    self._last_channel_metrics["cache"]["hit"] = True
                    self._last_channel_metrics["cache"].pop("skip_reason", None)
            except Exception as exc:
                logger.debug(NON_CRITICAL_RETRIEVER_FALLBACK_LOG, exc)
            return cached[:top_k]

        # Semantic cache (best-effort): lookup only after exact cache miss.
        if semantic_cache_eligible and corpus_cache_token:
            try:
                from app.services.semantic_cache import get_cached_semantic_payload

                semantic_cached, sem_meta = get_cached_semantic_payload(
                    tenant_id=str(tenant_uuid),
                    account_id=account_id0,
                    dataset_id=dataset_id0,
                    corpus_cache_token=str(corpus_cache_token),
                    behavior_hash=behavior_hash,
                    query=query,
                    top_k=int(top_k or 0),
                    score_threshold=float(score_threshold or 0.0),
                    retrieval_mode=retrieval_mode,
                    metadata_filter=full_metadata_filter if isinstance(full_metadata_filter, dict) else None,
                    document_ids=doc_ids,
                )
                if isinstance(sem_meta, dict):
                    cache_meta["semantic"].update(sem_meta)
            except Exception as exc:
                _log_retriever_fallback('_hybrid_search', exc)
                semantic_cached = None
                cache_meta["semantic"]["skip_reason"] = "lookup_error"

        if semantic_cached:
            semantic_cache_hit = True
            try:
                if isinstance(self._last_channel_metrics, dict):
                    self._last_channel_metrics.setdefault("cache", {})  # type: ignore[call-arg]
                    self._last_channel_metrics["cache"]["semantic"]["hit"] = True
                    self._last_channel_metrics["cache"]["semantic"].pop("skip_reason", None)
            except Exception as exc:
                logger.debug(NON_CRITICAL_RETRIEVER_FALLBACK_LOG, exc)
            return semantic_cached[:top_k]

        singleflight_leader = False
        distributed_singleflight_lease = None
        if distributed_singleflight_eligible and cache_key and not cache_hit:
            local_singleflight_leader = False
            try:
                singleflight_leader, inflight_future = acquire_inflight_retrieval_candidates(cache_key)
                local_singleflight_leader = bool(singleflight_leader)
                if not singleflight_leader:
                    wait_started_at = time.perf_counter()
                    try:
                        shared_payload = wait_for_inflight_retrieval_candidates(
                            cache_key,
                            inflight_future,
                            timeout_sec=max(
                                1.0,
                                float(
                                    getattr(
                                        settings,
                                        "RETRIEVAL_CANDIDATE_SINGLEFLIGHT_WAIT_TIMEOUT_SEC",
                                        60.0,
                                    )
                                    or 60.0
                                ),
                            ),
                        )
                    finally:
                        cache_meta["local_singleflight_wait_ms"] = round(
                            max(0.0, (time.perf_counter() - wait_started_at) * 1000.0),
                            1,
                        )
                    if isinstance(shared_payload, list):
                        cache_meta["singleflight_hit"] = True
                        cache_meta["singleflight_role"] = "follower"
                        return shared_payload[:top_k]
                cache_meta["singleflight_role"] = "leader"
                distributed_wait_started_at = time.perf_counter()
                try:
                    distributed_leader, distributed_payload, distributed_singleflight_lease = (
                        acquire_or_wait_for_distributed_inflight_retrieval_candidates(cache_key)
                    )
                finally:
                    cache_meta["distributed_singleflight_wait_ms"] = round(
                        max(0.0, (time.perf_counter() - distributed_wait_started_at) * 1000.0),
                        1,
                    )
                if not distributed_leader:
                    if isinstance(distributed_payload, list):
                        cache_meta["singleflight_hit"] = True
                        cache_meta["singleflight_role"] = "follower"
                        cache_meta["distributed_singleflight_hit"] = True
                        resolve_inflight_retrieval_candidates(cache_key, distributed_payload)
                        return distributed_payload[:top_k]
                    singleflight_leader = False
            except RetrievalCandidateSingleflightTimeoutError:
                raise
            except Exception as exc:
                _log_retriever_fallback('_hybrid_search', exc)
                singleflight_leader = local_singleflight_leader
                distributed_singleflight_lease = None

        emit_stream_event("event", {"message": "正在召回候选…"}, dedupe_key="retrieval.recall")

        # MMR mode needs more candidates for diversity selection
        fetch_k = top_k * 2
        if retrieval_mode == "mmr":
            fetch_k = top_k * max(1, mmr_fetch_k_multiplier)

        # 1) Vector retrieval
        vector_results: list[dict[str, Any]] = []
        vector_shard_failed = False
        vector_shard_admission_timeout: RetrievalAdmissionTimeoutError | None = None
        if want_vector:
            vector_store = get_vector_store()
            channel_health.started("vector")
            try:
                t0 = time.perf_counter()
                try:
                    if runtime_scope_ids and not runtime_shards:
                        channel_health.failed("vector", LookupError("MissingDatasetRuntime"))
                        vector_results = []
                    elif runtime_shards:
                        vector_results, shard_failures = self._search_vector_runtime_shards(
                            query=query,
                            top_k=fetch_k,
                            score_threshold=score_threshold,
                            document_ids=document_ids,
                            tenant_id=tenant_uuid,
                            metadata_filter=bm25_filter,
                            runtime_shards=runtime_shards,
                            vector_store=vector_store,
                        )
                        for exc in shard_failures:
                            channel_health.failed("vector", exc)
                            if vector_shard_admission_timeout is None and isinstance(exc, RetrievalAdmissionTimeoutError):
                                vector_shard_admission_timeout = exc
                        vector_shard_failed = bool(shard_failures)
                        if runtime_scope_missing_dataset_ids:
                            channel_health.failed("vector", LookupError("MissingDatasetRuntime"))
                            vector_shard_failed = True
                        if len(shard_failures) < len(runtime_shards):
                            channel_health.succeeded("vector")
                    elif embedding_runtime.dataset_scoped:
                        vector_results = self._search_dataset_scoped_vectors(
                            query=query,
                            top_k=fetch_k,
                            score_threshold=score_threshold,
                            document_ids=document_ids,
                            tenant_id=tenant_uuid,
                            metadata_filter=vector_filter,
                            embedding_runtime=embedding_runtime,
                        )
                        vector_results = self._tag_vector_hits_with_expected_space(
                            vector_results,
                            expected_space=str(embedding_runtime.embedding_space_hash or "").strip(),
                        )
                    else:
                        search_kwargs = {
                            "query": query,
                            "top_k": fetch_k,
                            "score_threshold": score_threshold,
                            "document_ids": document_ids,
                            "tenant_id": tenant_uuid,
                        }
                        if vector_filter:
                            search_kwargs["metadata_filter"] = vector_filter
                        vector_results = vector_store.search(**search_kwargs)
                    if not runtime_shards:
                        channel_health.succeeded("vector")
                finally:
                    vector_elapsed_ms += (time.perf_counter() - t0) * 1000
            except Exception as exc:
                channel_health.failed("vector", exc)
                logger.warning("Vector search failed: %s", exc)
                vector_results = []

        # Optional: ColBERT ANN fallback for vector retrieval.
        # This is opt-in and only runs when vector backend returns empty results.
        if want_vector and not vector_results and bool(getattr(settings, "COLBERT_RETRIEVAL_ENABLED", False)):
            channel_health.started("colbert")
            try:
                t0 = time.perf_counter()
                try:
                    vector_results = self._search_colbert_ann(
                        query=query,
                        top_k=fetch_k,
                        document_ids=document_ids,
                        tenant_id=tenant_uuid,
                        metadata_filter=bm25_filter,
                    )
                    colbert_used = True
                    colbert_candidates = int(len(vector_results or []))
                    channel_health.succeeded("colbert")
                finally:
                    delta_ms = (time.perf_counter() - t0) * 1000
                    vector_elapsed_ms += delta_ms
                    colbert_elapsed_ms += delta_ms
            except Exception as exc:
                channel_health.failed("colbert", exc)
                logger.warning("ColBERT ANN search failed: %s", exc)
                vector_results = []

        bm25_results: list[dict[str, Any]] = []
        lexical_results: list[dict[str, Any]] = []
        lexical_run_reason = "not_run"
        lexical_hybrid_fallback_only = (
            bool(self.lexical_db_hybrid_fallback_only)
            if self.lexical_db_hybrid_fallback_only is not None
            else bool(getattr(settings, "LEXICAL_DB_HYBRID_FALLBACK_ONLY", True))
        )
        if retrieval_mode == "keyword":
            if want_lexical:
                channel_health.started("lexical_db")
                t0 = time.perf_counter()
                try:
                    lexical_results = self._search_lexical_db(
                        query=query,
                        top_k=fetch_k,
                        document_ids=document_ids,
                        tenant_id=tenant_uuid,
                        metadata_filter=bm25_filter,
                    )
                    channel_health.succeeded("lexical_db")
                    lexical_run_reason = "keyword_primary"
                except Exception as exc:
                    channel_health.failed("lexical_db", exc)
                    logger.warning(LEXICAL_DB_SEARCH_FAILED_LOG, exc)
                    lexical_results = []
                    lexical_run_reason = "error"
                finally:
                    lexical_elapsed_ms += (time.perf_counter() - t0) * 1000
            if want_bm25 or (not lexical_results and bm25_index_enabled):
                channel_health.started("bm25")
                t0 = time.perf_counter()
                try:
                    bm25_results = self._search_bm25(
                        query=query,
                        top_k=fetch_k,
                        document_ids=document_ids,
                        tenant_id=tenant_uuid,
                        metadata_filter=bm25_filter,
                    )
                    channel_health.succeeded("bm25")
                except Exception as exc:
                    channel_health.failed("bm25", exc)
                    logger.warning("BM25 search failed: %s", exc)
                    bm25_results = []
                finally:
                    bm25_elapsed_ms += (time.perf_counter() - t0) * 1000
        else:
            # 2) BM25 retrieval
            if want_bm25:
                channel_health.started("bm25")
                t0 = time.perf_counter()
                try:
                    bm25_results = self._search_bm25(
                        query=query,
                        top_k=fetch_k,
                        document_ids=document_ids,
                        tenant_id=tenant_uuid,
                        metadata_filter=bm25_filter,
                    )
                    channel_health.succeeded("bm25")
                except Exception as exc:
                    channel_health.failed("bm25", exc)
                    logger.warning("BM25 search failed: %s", exc)
                    bm25_results = []
                finally:
                    bm25_elapsed_ms += (time.perf_counter() - t0) * 1000

            # 2b) Persistent lexical fallback (Postgres FTS / pg_trgm).
            #
            # Hybrid/MMR usually already has dense vector + in-memory BM25 coverage.
            # Running pg_trgm on every query is expensive on large datasets, so keep it
            # as a recall safety net unless explicitly configured to run in parallel.
            primary_candidate_count = len(vector_results or []) + len(bm25_results or [])
            metadata_exact_fallback_enabled = (
                bool(self.lexical_db_hybrid_metadata_exact_fallback_enabled)
                if self.lexical_db_hybrid_metadata_exact_fallback_enabled is not None
                else bool(getattr(settings, "LEXICAL_DB_HYBRID_METADATA_EXACT_FALLBACK_ENABLED", True))
            )
            metadata_exact_anchor_like_query = bool(
                metadata_exact_fallback_enabled and _query_looks_like_cjk_metadata_anchor(query)
            )
            primary_has_metadata_exact_anchor = False
            if metadata_exact_anchor_like_query:
                primary_has_metadata_exact_anchor = _results_contain_metadata_exact_anchor(
                    query,
                    list(vector_results or []) + list(bm25_results or []),
                    limit=max(1, int(top_k or 0)),
                )
            metadata_exact_fallback = bool(
                lexical_hybrid_fallback_only
                and metadata_exact_anchor_like_query
            )
            should_run_lexical = bool(want_lexical) and (
                not lexical_hybrid_fallback_only or primary_candidate_count < max(1, int(top_k or 0))
                or metadata_exact_fallback
            )
            if should_run_lexical:
                channel_health.started("lexical_db")
                t0 = time.perf_counter()
                try:
                    lexical_results = self._search_lexical_db(
                        query=query,
                        top_k=fetch_k,
                        document_ids=document_ids,
                        tenant_id=tenant_uuid,
                        metadata_filter=bm25_filter,
                    )
                    channel_health.succeeded("lexical_db")
                    if not lexical_hybrid_fallback_only:
                        lexical_run_reason = "hybrid_parallel"
                    elif metadata_exact_fallback:
                        lexical_run_reason = "hybrid_metadata_exact_fallback"
                    else:
                        lexical_run_reason = "hybrid_fallback"
                except Exception as exc:
                    channel_health.failed("lexical_db", exc)
                    logger.warning(LEXICAL_DB_SEARCH_FAILED_LOG, exc)
                    lexical_results = []
                    lexical_run_reason = "error"
                finally:
                    lexical_elapsed_ms += (time.perf_counter() - t0) * 1000
            elif want_lexical:
                lexical_run_reason = "skipped_primary_candidates_sufficient"

            metadata_exact_db_results: list[dict[str, Any]] = []
            metadata_exact_db_enabled = (
                bool(self.metadata_exact_db_fallback_enabled)
                if self.metadata_exact_db_fallback_enabled is not None
                else bool(getattr(settings, "RETRIEVAL_METADATA_EXACT_DB_FALLBACK_ENABLED", True))
            )
            metadata_exact_db_reason = "not_run"
            if metadata_exact_db_enabled and metadata_exact_fallback:
                lexical_has_metadata_exact_anchor = _results_contain_metadata_exact_anchor(
                    query,
                    lexical_results,
                    limit=max(1, int(top_k or 0)),
                )
                t0 = time.perf_counter()
                try:
                    metadata_exact_db_results = self._search_metadata_exact_anchor_db(
                        query=query,
                        top_k=fetch_k,
                        document_ids=document_ids,
                        tenant_id=tenant_uuid,
                        metadata_filter=bm25_filter,
                    )
                    metadata_exact_db_reason = (
                        "hybrid_metadata_exact_fallback_enrich"
                        if lexical_has_metadata_exact_anchor
                        else "hybrid_metadata_exact_fallback"
                    )
                except Exception as exc:
                    logger.debug("Metadata exact DB fallback failed: %s", exc)
                    metadata_exact_db_results = []
                    metadata_exact_db_reason = "error"
                finally:
                    lexical_elapsed_ms += (time.perf_counter() - t0) * 1000

                if metadata_exact_db_results:
                    seen_chunk_ids = {
                        str((item.get("metadata") or {}).get("chunk_id") or item.get("chunk_id") or "")
                        for item in lexical_results
                        if isinstance(item, dict)
                    }
                    for item in metadata_exact_db_results:
                        cid = str((item.get("metadata") or {}).get("chunk_id") or item.get("chunk_id") or "")
                        if cid and cid in seen_chunk_ids:
                            continue
                        if cid:
                            seen_chunk_ids.add(cid)
                        lexical_results.append(item)
                        metadata_exact_protected_results.append(item)
            elif not metadata_exact_db_enabled:
                metadata_exact_db_reason = "disabled"

            if want_lexical and isinstance(self._last_channel_metrics, dict):
                self._last_channel_metrics["lexical_metadata_exact_fallback"] = {
                    "enabled": bool(metadata_exact_fallback_enabled),
                    "query_anchor_like": bool(metadata_exact_anchor_like_query),
                    "primary_has_exact_anchor": bool(primary_has_metadata_exact_anchor),
                    "triggered": bool(metadata_exact_fallback),
                }
                self._last_channel_metrics["metadata_exact_db"] = {
                    "enabled": bool(metadata_exact_db_enabled),
                    "used": bool(metadata_exact_db_results),
                    "candidates": int(len(metadata_exact_db_results or [])),
                    "run_reason": metadata_exact_db_reason,
                }

        # 2c) Optional sparse channel (SPLADE-style)
        sparse_results: list[dict[str, Any]] = []
        self._last_sparse_provider_status = self._resolve_sparse_provider_status(
            sparse_enabled=self._effective_sparse_enabled()
        )
        if not want_sparse:
            self._last_sparse_provider_status = {
                **(self._last_sparse_provider_status or {}),
                "outcome": "skipped",
                "candidates": 0,
            }
        if want_sparse:
            channel_health.started("sparse")
            try:
                sparse_results = self._search_sparse(
                    query=query,
                    top_k=fetch_k,
                    document_ids=document_ids,
                    tenant_id=tenant_uuid,
                    metadata_filter=bm25_filter,
                )
                channel_health.succeeded("sparse")
            except Exception as exc:
                channel_health.failed("sparse", exc)
                logger.warning("Sparse search failed: %s", exc)
                sparse_results = []

        if want_colpali:
            channel_health.started("colpali")
            try:
                colpali_results = self._search_colpali_retriever(
                    query=query,
                    top_k=fetch_k,
                    document_ids=document_ids,
                    tenant_id=tenant_uuid,
                    metadata_filter=bm25_filter,
                )
                channel_health.succeeded("colpali")
            except Exception as exc:
                channel_health.failed("colpali", exc)
                logger.warning("ColPali retriever failed: %s", exc)
                colpali_results = []

        # Fallback: when single-channel mode fails, try the other channel.
        if retrieval_mode == "vector" and (not vector_results or vector_shard_failed):
            channel_health.started("bm25")
            t0 = time.perf_counter()
            try:
                bm25_results = self._search_bm25(
                    query=query,
                    top_k=fetch_k,
                    document_ids=document_ids,
                    tenant_id=tenant_uuid,
                    metadata_filter=bm25_filter,
                )
                channel_health.succeeded("bm25")
            except Exception as exc:
                channel_health.failed("bm25", exc)
                logger.warning("BM25 search failed: %s", exc)
                bm25_results = []
            finally:
                bm25_elapsed_ms += (time.perf_counter() - t0) * 1000
            channel_health.started("lexical_db")
            try:
                t0 = time.perf_counter()
                lexical_results = self._search_lexical_db(
                    query=query,
                    top_k=fetch_k,
                    document_ids=document_ids,
                    tenant_id=tenant_uuid,
                    metadata_filter=bm25_filter,
                )
                channel_health.succeeded("lexical_db")
                lexical_run_reason = "vector_fallback"
            except Exception as exc:
                channel_health.failed("lexical_db", exc)
                logger.warning(LEXICAL_DB_SEARCH_FAILED_LOG, exc)
                lexical_results = []
                lexical_run_reason = "error"
            finally:
                lexical_elapsed_ms += (time.perf_counter() - t0) * 1000
            if want_sparse:
                channel_health.started("sparse")
                try:
                    sparse_results = self._search_sparse(
                        query=query,
                        top_k=fetch_k,
                        document_ids=document_ids,
                        tenant_id=tenant_uuid,
                        metadata_filter=bm25_filter,
                    )
                    channel_health.succeeded("sparse")
                except Exception as exc:
                    channel_health.failed("sparse", exc)
                    logger.warning("Sparse search failed: %s", exc)
                    sparse_results = []
        elif retrieval_mode == "keyword" and not bm25_results and not lexical_results and not sparse_results:
            vector_store = get_vector_store()
            channel_health.started("vector")
            try:
                t0 = time.perf_counter()
                try:
                    if runtime_scope_ids and not runtime_shards:
                        channel_health.failed("vector", LookupError("MissingDatasetRuntime"))
                        vector_results = []
                    elif runtime_shards:
                        vector_results, shard_failures = self._search_vector_runtime_shards(
                            query=query,
                            top_k=fetch_k,
                            score_threshold=score_threshold,
                            document_ids=document_ids,
                            tenant_id=tenant_uuid,
                            metadata_filter=bm25_filter,
                            runtime_shards=runtime_shards,
                            vector_store=vector_store,
                        )
                        for exc in shard_failures:
                            channel_health.failed("vector", exc)
                            if vector_shard_admission_timeout is None and isinstance(exc, RetrievalAdmissionTimeoutError):
                                vector_shard_admission_timeout = exc
                        if runtime_scope_missing_dataset_ids:
                            channel_health.failed("vector", LookupError("MissingDatasetRuntime"))
                        if len(shard_failures) < len(runtime_shards):
                            channel_health.succeeded("vector")
                    elif embedding_runtime.dataset_scoped:
                        vector_results = self._search_dataset_scoped_vectors(
                            query=query,
                            top_k=fetch_k,
                            score_threshold=score_threshold,
                            document_ids=document_ids,
                            tenant_id=tenant_uuid,
                            metadata_filter=vector_filter,
                            embedding_runtime=embedding_runtime,
                        )
                        vector_results = self._tag_vector_hits_with_expected_space(
                            vector_results,
                            expected_space=str(embedding_runtime.embedding_space_hash or "").strip(),
                        )
                        channel_health.succeeded("vector")
                    else:
                        fallback_kwargs = {
                            "query": query,
                            "top_k": fetch_k,
                            "score_threshold": score_threshold,
                            "document_ids": document_ids,
                            "tenant_id": tenant_uuid,
                        }
                        if vector_filter:
                            fallback_kwargs["metadata_filter"] = vector_filter
                        vector_results = vector_store.search(**fallback_kwargs)
                        channel_health.succeeded("vector")
                finally:
                    vector_elapsed_ms += (time.perf_counter() - t0) * 1000
            except Exception as exc:
                channel_health.failed("vector", exc)
                logger.warning("Vector search failed: %s", exc)
                vector_results = []

        channel_health.publish(channel_metrics)

        if (
            vector_shard_admission_timeout is not None
            and not vector_results
            and not bm25_results
            and not lexical_results
            and not sparse_results
            and not colpali_results
        ):
            if singleflight_leader and cache_key:
                reject_current_inflight_retrieval_candidates(vector_shard_admission_timeout)
            release_distributed_inflight_retrieval_candidates(distributed_singleflight_lease)
            raise vector_shard_admission_timeout

        prepared_channel_results = prepare_hybrid_channel_results(
            query=query,
            vector_results=vector_results,
            bm25_results=bm25_results,
            lexical_results=lexical_results,
            sparse_results=sparse_results,
            document_ids=document_ids,
            vector_filter=vector_filter,
            runtime_shards_present=bool(runtime_shards),
            chunk_id_lookup=self._chunk_id_lookup.get(self._tenant_key(tenant_id)) or {},
            match_metadata_filter=self._match_metadata_filter,
            metadata_exact_pre_fusion_enabled=bool(getattr(settings, "RETRIEVAL_METADATA_EXACT_PRE_FUSION_ENABLED", False)),
            phrase_boost_weight=max(
                0.0,
                float(getattr(settings, "RETRIEVAL_EXACT_PHRASE_RERANK_BOOST", 0.35) or 0.0),
            ),
        )
        vector_results = prepared_channel_results.vector_results
        bm25_results = prepared_channel_results.bm25_results
        lexical_results = prepared_channel_results.lexical_results
        sparse_results = prepared_channel_results.sparse_results
        metadata_exact_pre_fusion_stats = prepared_channel_results.metadata_exact_pre_fusion_stats

        # Per-query channel metrics (best-effort): used by evidence/debug endpoints.
        try:
            update_hybrid_channel_diagnostics(
                channel_metrics=channel_metrics,
                vector_results=vector_results,
                bm25_results=bm25_results,
                lexical_results=lexical_results,
                sparse_results=sparse_results,
                colpali_results=colpali_results,
                vector_elapsed_ms=vector_elapsed_ms,
                colbert_elapsed_ms=colbert_elapsed_ms,
                bm25_elapsed_ms=bm25_elapsed_ms,
                lexical_elapsed_ms=lexical_elapsed_ms,
                colbert_candidates=colbert_candidates,
                colbert_used=colbert_used,
                colbert_retrieval_enabled=bool(getattr(settings, "COLBERT_RETRIEVAL_ENABLED", False)),
                colbert_provider=str(getattr(settings, "COLBERT_RETRIEVAL_PROVIDER", "") or ""),
                retrieval_mode=retrieval_mode,
                fusion_strategy=str(self.fusion_strategy or ""),
                rrf_k=int(self.rrf_k or 0),
                fusion_weights=(
                    dict(getattr(self, "fusion_weights", None))
                    if isinstance(getattr(self, "fusion_weights", None), dict)
                    else None
                ),
                vector_backend=str(getattr(settings, "VECTOR_BACKEND", "") or ""),
                want_vector=bool(want_vector),
                want_bm25=bool(want_bm25),
                want_lexical=bool(want_lexical),
                want_sparse=bool(want_sparse),
                want_colpali=bool(want_colpali),
                vector_filter_applied=bool(vector_filter),
                bm25_filter_applied=bool(bm25_filter),
                bm25_index_enabled=bool(bm25_index_enabled),
                last_bm25_status=dict(self._last_bm25_status or {}),
                lexical_run_reason=lexical_run_reason,
                lexical_hybrid_fallback_only=bool(lexical_hybrid_fallback_only),
                lexical_db_enabled=bool(lexical_db_enabled),
                lexical_db_fts_config=str(getattr(settings, "LEXICAL_DB_FTS_CONFIG", "simple") or "simple"),
                lexical_db_trgm_enabled=bool(getattr(settings, "LEXICAL_DB_TRGM_ENABLED", True)),
                lexical_pg_trgm_available=self._lexical_pg_trgm_available,
                metadata_exact_pre_fusion_stats=dict(metadata_exact_pre_fusion_stats),
                colpali_reason=colpali_reason,
                sparse_provider_status=dict(self._last_sparse_provider_status or {}),
                sparse_provider=self.sparse_provider,
                keyword_strategy=keyword_strategy,
            )
        except Exception:
            # Keep the stable shape even if richer channel details fail.
            try:
                timing = channel_metrics.get("timing")
                if isinstance(timing, dict):
                    timing["vector_ms"] = round(float(vector_elapsed_ms), 2)
                    timing["colbert_ms"] = round(float(colbert_elapsed_ms), 2)
                    timing["bm25_ms"] = round(float(bm25_elapsed_ms), 2)
                    timing["lexical_ms"] = round(float(lexical_elapsed_ms), 2)
                counts = channel_metrics.get("counts")
                if isinstance(counts, dict):
                    counts["vector_candidates"] = int(len(vector_results or []))
                    counts["colbert_candidates"] = int(colbert_candidates or 0)
                    counts["colpali_candidates"] = int(len(colpali_results or []))
                    counts["bm25_candidates"] = int(len(bm25_results or []))
                    counts["lexical_candidates"] = int(len(lexical_results or []))
                    counts["sparse_candidates"] = int(len(sparse_results or []))
            except Exception as exc:
                logger.debug(NON_CRITICAL_RETRIEVER_FALLBACK_LOG, exc)

        # 3) Score normalization + linear merge
        t_fusion0 = time.perf_counter()
        merged_results = self._merge_results(
            vector_results,
            bm25_results,
            list(lexical_results or []) + list(colpali_results or []),
            sparse_results,
            query=query,
            alpha=alpha,
            fusion_strategy=self.fusion_strategy,
            rrf_k=self.rrf_k,
            top_k=top_k,
        )

        if metadata_exact_protected_results:
            merged_keys = {self._result_key(item) for item in merged_results if isinstance(item, dict)}
            protected_added = 0
            for item in metadata_exact_protected_results:
                if not isinstance(item, dict):
                    continue
                key = self._result_key(item)
                if key in merged_keys:
                    continue
                merged_keys.add(key)
                merged_results.append(dict(item))
                protected_added += 1
            if protected_added and isinstance(self._last_channel_metrics, dict):
                metadata_exact_meta = self._last_channel_metrics.setdefault("metadata_exact_db", {})
                if isinstance(metadata_exact_meta, dict):
                    metadata_exact_meta["protected_added"] = int(protected_added)

        try:
            if isinstance(self._last_channel_metrics, dict):
                self._last_channel_metrics["merged_pre_dedup"] = len(merged_results or [])
        except Exception as exc:
            logger.debug(NON_CRITICAL_RETRIEVER_FALLBACK_LOG, exc)

        exact_anchor_pre_dedup_stats: dict[str, Any] = {}
        merged_results = self._apply_metadata_exact_anchor_post_ordering(
            query,
            merged_results,
            stats=exact_anchor_pre_dedup_stats,
        )
        if exact_anchor_pre_dedup_stats:
            try:
                if isinstance(self._last_channel_metrics, dict):
                    self._last_channel_metrics["metadata_exact_pre_dedup_ordering"] = exact_anchor_pre_dedup_stats
            except Exception as exc:
                logger.debug(NON_CRITICAL_RETRIEVER_FALLBACK_LOG, exc)

        merged_results = self._deduplicate_results(merged_results)

        try:
            if isinstance(self._last_channel_metrics, dict):
                self._last_channel_metrics["merged_post_dedup"] = len(merged_results or [])
        except Exception as exc:
            logger.debug(NON_CRITICAL_RETRIEVER_FALLBACK_LOG, exc)
        try:
            timing = channel_metrics.get("timing")
            if isinstance(timing, dict):
                timing["fusion_ms"] = round(float((time.perf_counter() - t_fusion0) * 1000), 2)
        except Exception as exc:
            logger.debug(NON_CRITICAL_RETRIEVER_FALLBACK_LOG, exc)

        # 4) Reranking strategy
        if merged_results:
            emit_stream_event("event", {"message": "候选召回完成，正在重排…"}, dedupe_key="retrieval.rerank")
        if retrieval_mode == "mmr" and merged_results:
            merged_results = self._mmr_rerank(merged_results, query=query, top_k=top_k, lambda_mult=mmr_lambda)
        elif enable_weight_rerank and merged_results:
            merged_results = self._weight_rerank(
                query=query,
                documents=merged_results,
                vector_weight=vector_weight,
                keyword_weight=keyword_weight,
            )

        # 5) Optional: LLM Reranker refinement (executed before final truncation)
        if merged_results and bool(self.enable_reranker):
            rerank_meta: dict[str, Any] = {
                "enabled": True,
                "provider": None,
                "top_n_config": int(self.reranker_top_n or 0),
                "candidates_n": 0,
                "used": False,
                "elapsed_sec": 0.0,
                "model_used": None,
                "error": None,
                "skip_reason": None,
                "skip_top_score": None,
                "skip_score_gap": None,
            }
            provider = (self.reranker_provider or settings.RERANKER_PROVIDER or "llm").lower()
            rerank_meta["provider"] = provider
            if provider in ("none", "off", "false", "0"):
                rerank_meta["skip_reason"] = "provider_off"
            else:
                # Budget governance:
                # - `top_k` here is the *search_k* (may be overfetch-expanded for trimming).
                # - Rerank should be governed by the *requested_k* to avoid overfetch inflating cost.
                final_k = int(requested_k) if requested_k is not None else int(top_k or 0)
                final_k = max(1, final_k)

                candidates_n = int(self.reranker_top_n or settings.RERANKER_TOP_N or 20)
                candidates_n = max(candidates_n, final_k)
                candidates_n = min(candidates_n, len(merged_results))
                rerank_meta["candidates_n"] = int(candidates_n)

                conditional_rerank_enabled = bool(getattr(settings, "RERANK_CONDITIONAL_ENABLED", False))
                top_score = float(merged_results[0].get("score", 0.0) or 0.0)
                second_score = float(merged_results[1].get("score", 0.0) or 0.0) if len(merged_results) > 1 else 0.0
                score_gap = top_score - second_score
                rerank_meta["skip_top_score"] = round(float(top_score), 6)
                rerank_meta["skip_score_gap"] = round(float(score_gap), 6)
                skip_threshold = float(getattr(settings, "RERANK_SKIP_THRESHOLD", 0.85) or 0.85)
                skip_gap = float(getattr(settings, "RERANK_SKIP_GAP", 0.15) or 0.15)
                if conditional_rerank_enabled and top_score >= skip_threshold and score_gap >= skip_gap:
                    rerank_meta["skip_reason"] = "high_confidence"
                    try:
                        if isinstance(self._last_channel_metrics, dict):
                            self._last_channel_metrics["rerank"] = rerank_meta
                    except Exception as exc:
                        logger.debug(NON_CRITICAL_RETRIEVER_FALLBACK_LOG, exc)
                    if isinstance(self._last_channel_metrics, dict):
                        self._last_channel_metrics["merged_post_rerank"] = len(merged_results or [])
                else:
                    reranker = get_reranker(provider)

                    candidates: list[RerankCandidate] = []
                    id_to_doc: dict[str, dict[str, Any]] = {}
                    for doc in merged_results[:candidates_n]:
                        rid = self._result_key(doc)
                        text = self._rerank_text_from_result(doc)
                        if not rid or not text:
                            continue
                        meta = dict(doc.get("metadata") or {})
                        meta["score"] = float(doc.get("score", 0.0) or 0.0)
                        candidates.append(RerankCandidate(id=rid, text=text, metadata=meta))
                        id_to_doc[rid] = doc

                    if not candidates:
                        rerank_meta["skip_reason"] = "no_candidates"
                    else:
                        try:
                            start = time.time()
                            result = reranker.rerank(
                                query=query,
                                candidates=candidates,
                                top_n=candidates_n,
                                tenant_id=str(self.tenant_id or "").strip() or None,
                                query_type=None,
                            )
                            rerank_elapsed = result.elapsed_sec or (time.time() - start)
                            rerank_provider = result.provider or provider

                            rerank_meta["used"] = True
                            rerank_meta["elapsed_sec"] = round(float(rerank_elapsed), 3)
                            rerank_meta["model_used"] = result.model_used
                            rerank_meta["provider"] = rerank_provider

                            ordered = []
                            used: set[str] = set()
                            boosted_after_rerank = 0
                            phrase_boost_weight = max(
                                0.0,
                                float(getattr(settings, "RETRIEVAL_EXACT_PHRASE_RERANK_BOOST", 0.35) or 0.0),
                            )
                            for rid in result.ordered_ids:
                                d = id_to_doc.get(rid)
                                if not d or rid in used:
                                    continue
                                used.add(rid)
                                new_doc = dict(d)
                                new_doc["retrieval_score"] = float(new_doc.get("score", 0.0) or 0.0)
                                if rid in result.score_map:
                                    rerank_score = float(result.score_map[rid])
                                    new_doc["rerank_score"] = rerank_score
                                    phrase_boost = float(new_doc.get("exact_phrase_boost") or 0.0)
                                    metadata_boost = 0.0
                                    if _apply_metadata_exact_anchor_to_result(
                                        query=query,
                                        result=new_doc,
                                        phrase_boost_weight=phrase_boost_weight,
                                    ):
                                        metadata_boost = float(new_doc.get("metadata_exact_match_boost") or 0.0)
                                    final_score = min(1.0, float(rerank_score) + float(phrase_boost) + float(metadata_boost))
                                    new_doc["score"] = float(final_score)
                                    if phrase_boost > 0.0 or metadata_boost > 0.0:
                                        new_doc["rerank_score_final"] = float(final_score)
                                        boosted_after_rerank += 1
                                new_doc["reranker_provider"] = rerank_provider
                                new_doc["rerank_elapsed_sec"] = round(float(rerank_elapsed), 3)
                                new_doc["rerank_model_used"] = result.model_used
                                ordered.append(new_doc)

                            if boosted_after_rerank > 0:
                                ordered = sorted(ordered, key=lambda x: (-float(x.get("score", 0.0) or 0.0), self._result_key(x)))
                                rerank_meta["post_rerank_exact_boosted"] = int(boosted_after_rerank)

                            # Append candidates not returned by reranker (maintain original order)
                            for doc in merged_results[:candidates_n]:
                                rid = self._result_key(doc)
                                if rid in used:
                                    continue
                                new_doc = dict(doc)
                                new_doc.setdefault("reranker_provider", rerank_provider)
                                new_doc.setdefault("rerank_elapsed_sec", round(float(rerank_elapsed), 3))
                                new_doc.setdefault("rerank_model_used", result.model_used)
                                ordered.append(new_doc)

                            merged_results = ordered + merged_results[candidates_n:]
                        except Exception as exc:
                            rerank_meta["used"] = False
                            rerank_meta["error"] = str(exc)[:200]
                            rerank_meta["skip_reason"] = "error"
                            logger.warning("Reranker failed (%s): %s", provider, exc)
                            for doc in merged_results[:candidates_n]:
                                meta = dict(doc.get("metadata") or {})
                                meta.setdefault("reranker_provider", provider)
                                meta.setdefault("reranker_error", str(exc)[:200])
                                doc["metadata"] = meta

            try:
                if isinstance(self._last_channel_metrics, dict):
                    self._last_channel_metrics["rerank"] = rerank_meta
            except Exception as exc:
                logger.debug(NON_CRITICAL_RETRIEVER_FALLBACK_LOG, exc)

        # Channel attribution (best-effort): count how many final candidates are supported by each channel.
        try:
            if isinstance(self._last_channel_metrics, dict):
                self._last_channel_metrics["merged_post_rerank"] = len(merged_results or [])
                attribution = {"vector": 0, "bm25": 0, "lexical_db": 0, "multi": 0}
                for doc in merged_results or []:
                    has_v = float(doc.get("vector_score", 0.0) or 0.0) > 0.0
                    has_b = float(doc.get("bm25_score", 0.0) or 0.0) > 0.0
                    has_l = float(doc.get("lexical_score", 0.0) or 0.0) > 0.0
                    n = int(has_v) + int(has_b) + int(has_l)
                    if has_v:
                        attribution["vector"] += 1
                    if has_b:
                        attribution["bm25"] += 1
                    if has_l:
                        attribution["lexical_db"] += 1
                    if n > 1:
                        attribution["multi"] += 1
                self._last_channel_metrics["attribution"] = attribution
        except Exception as exc:
            logger.debug(NON_CRITICAL_RETRIEVER_FALLBACK_LOG, exc)

        before_diversity = len(merged_results or [])
        div_caps: dict[str, Any] = {}
        merged_results = self._apply_document_diversity(merged_results, top_k=top_k, stats=div_caps)
        self._last_diversity_caps = div_caps
        if metadata_exact_protected_results:
            merged_keys = {self._result_key(item) for item in merged_results if isinstance(item, dict)}
            protected_added = 0
            for item in metadata_exact_protected_results:
                if not isinstance(item, dict):
                    continue
                key = self._result_key(item)
                if key in merged_keys:
                    continue
                merged_keys.add(key)
                merged_results.append(dict(item))
                protected_added += 1
            if protected_added and isinstance(self._last_channel_metrics, dict):
                metadata_exact_meta = self._last_channel_metrics.setdefault("metadata_exact_db", {})
                if isinstance(metadata_exact_meta, dict):
                    metadata_exact_meta["protected_after_diversity_added"] = int(protected_added)
        after_diversity = len(merged_results or [])
        try:
            if isinstance(self._last_channel_metrics, dict):
                self._last_channel_metrics["diversity"] = {
                    "before": int(before_diversity),
                    "after": int(after_diversity),
                    "dropped": int(max(0, before_diversity - after_diversity)),
                }
                self._last_channel_metrics["returned_top_k"] = int(min(int(top_k or 0), after_diversity))
        except Exception as exc:
            logger.debug(NON_CRITICAL_RETRIEVER_FALLBACK_LOG, exc)

        metadata_exact_final_stats: dict[str, Any] = {}
        merged_results = self._apply_metadata_exact_anchor_post_ordering(
            query,
            merged_results,
            stats=metadata_exact_final_stats,
        )
        if metadata_exact_final_stats:
            try:
                if isinstance(self._last_channel_metrics, dict):
                    self._last_channel_metrics["metadata_exact_final_ordering"] = metadata_exact_final_stats
            except Exception as exc:
                logger.debug(NON_CRITICAL_RETRIEVER_FALLBACK_LOG, exc)
        out = merged_results[:top_k]

        cache_store_allowed = not bool(channel_metrics.get("retrieval_degraded", False))
        if not cache_store_allowed:
            cache_meta["store_skip_reason"] = "retrieval_degraded"
            cache_meta["semantic"]["store_skip_reason"] = "retrieval_degraded"
        if cache_store_allowed and cache_eligible and (not cache_hit) and cache_key and out:
            try:
                stored = bool(set_cached_retrieval_candidates(cache_key, out))
                if isinstance(self._last_channel_metrics, dict):
                    self._last_channel_metrics.setdefault("cache", {})  # type: ignore[call-arg]
                    self._last_channel_metrics["cache"]["store_ok"] = stored
            except Exception as exc:
                logger.debug(NON_CRITICAL_RETRIEVER_FALLBACK_LOG, exc)
        if singleflight_leader and cache_key:
            if cache_store_allowed:
                publish_distributed_inflight_retrieval_candidates(cache_key, out)
                resolve_inflight_retrieval_candidates(cache_key, out)
            else:
                reject_current_inflight_retrieval_candidates(RuntimeError("retrieval degraded"))
            release_distributed_inflight_retrieval_candidates(distributed_singleflight_lease)
        if cache_store_allowed and semantic_cache_eligible and (not semantic_cache_hit) and corpus_cache_token and out:
            try:
                from app.services.semantic_cache import set_cached_semantic_payload

                stored = bool(
                    set_cached_semantic_payload(
                        tenant_id=str(tenant_uuid),
                        account_id=account_id0,
                        dataset_id=dataset_id0,
                        corpus_cache_token=str(corpus_cache_token),
                        behavior_hash=behavior_hash,
                        query=query,
                        top_k=int(top_k or 0),
                        score_threshold=float(score_threshold or 0.0),
                        retrieval_mode=retrieval_mode,
                        metadata_filter=full_metadata_filter if isinstance(full_metadata_filter, dict) else None,
                        document_ids=doc_ids,
                        payload=out,
                    )
                )
                if isinstance(self._last_channel_metrics, dict):
                    self._last_channel_metrics.setdefault("cache", {})  # type: ignore[call-arg]
                    self._last_channel_metrics["cache"].setdefault("semantic", {})  # type: ignore[call-arg]
                    self._last_channel_metrics["cache"]["semantic"]["store_ok"] = stored
            except Exception as exc:
                logger.debug(NON_CRITICAL_RETRIEVER_FALLBACK_LOG, exc)
        return out

    # ---- LangChain Retriever API ----

    def _get_relevant_documents(
        self,
        query: str,
        *,
        run_manager: CallbackManagerForRetrieverRun,
    ) -> list[Document]:
        max_query_chars = int(getattr(settings, "RETRIEVAL_QUERY_MAX_CHARS", 8_000) or 8_000)
        if len(str(query or "")) > max_query_chars:
            raise ValueError(f"retrieval query exceeds RETRIEVAL_QUERY_MAX_CHARS={max_query_chars}")

        # Deterministic query normalization applied upstream of all retrieval channels.
        # Keep the original for debugging/observability (stored in _last_debug_metrics below).
        from app.query.normalize import normalize_query

        query_norm = normalize_query(query)
        original_query = query
        query = query_norm.normalized_text

        # Defense-in-depth: avoid accidental tenant-level "open scope" retrieval.
        # Caller must explicitly scope retrieval via either:
        # - `document_ids`, or
        # - `dataset_id` (dataset boundary is the default enterprise safety posture).
        metadata_filter_dataset_scoped = bool(
            self.metadata_filter_enabled
            and _metadata_filter_has_dataset_scope(self.metadata_filter)
        )
        dataset_scope_ids = self._explicit_dataset_scope_ids()
        if not dataset_scope_ids and not (self.document_ids or []) and not metadata_filter_dataset_scoped:
            if not bool(getattr(settings, "CHAT_ALLOW_OPEN_SCOPE", False)):
                raise ValueError("dataset_id is required when document_ids is empty")

        requested_k = max(1, int(self.k or 0))
        hierarchy_family_collapse_enabled = self._should_apply_hierarchy_family_collapse()
        hierarchy_overfetch_factor = max(1, int(self.hierarchy_overfetch_factor or 1))
        # When running in open scope (no explicit document_ids), we may drop candidates due to:
        # - document/dataset ACL (security trimming)
        # - active pipeline version trimming
        # - metadata filtering (post-enrichment, especially for dotted `document_user.*` keys)
        # Over-fetch to keep enough final results after trimming.
        search_k = requested_k
        metadata_filter_requested = bool(
            self.metadata_filter_enabled
            and isinstance(self.metadata_filter, dict)
            and self.metadata_filter
        )
        if bool(self.enable_reranker):
            search_k = resolve_rerank_search_k(
                requested_k=search_k,
                profile=str(getattr(settings, "RERANK_PROFILE", "") or "").strip().lower() or None,
            )
        if hierarchy_family_collapse_enabled and hierarchy_overfetch_factor > 1:
            search_k = max(search_k, requested_k * hierarchy_overfetch_factor)
        overfetch_enabled = False
        overfetch_reasons: list[str] = []
        if not (self.document_ids or []):
            if not dataset_scope_ids and self.tenant_id and (self.account_id or "").strip():
                overfetch_enabled = True
                overfetch_reasons.append("open_scope_acl")
            if dataset_scope_ids or (self.tenant_id and (self.account_id or "").strip()):
                overfetch_enabled = True
                overfetch_reasons.append("active_pipeline")
            if metadata_filter_requested:
                overfetch_enabled = True
                overfetch_reasons.append("metadata_filter")

        if overfetch_enabled:
            mult_source = (
                self.retrieval_overfetch_multiplier
                if self.retrieval_overfetch_multiplier is not None
                else getattr(settings, "RETRIEVAL_OVERFETCH_MULTIPLIER", 1)
            )
            mult = max(1, int(mult_source or 1))
            if mult > 1:
                search_k = max(search_k, requested_k * mult)
            cap_source = (
                self.retrieval_overfetch_max_k
                if self.retrieval_overfetch_max_k is not None
                else getattr(settings, "RETRIEVAL_OVERFETCH_MAX_K", 0)
            )
            cap = int(cap_source or 0)
            if cap > 0:
                search_k = min(search_k, cap)

        # Unified candidate-fetch budget (used by vector/BM25/lexical/sparse channels).
        # Exposed in retriever_debug for evidence/diagnostics (PII-safe).
        fetch_k = int(search_k) * 2
        if str(self.retrieval_mode or "").strip().lower() == "mmr":
            fetch_k = int(search_k) * max(1, int(self.mmr_fetch_k_multiplier or 0))

        if self.document_ids:
            scope_kind = "document_ids"
        elif self.dataset_id is not None:
            scope_kind = "dataset_id"
        elif dataset_scope_ids:
            scope_kind = "dataset_ids"
        elif metadata_filter_dataset_scoped:
            scope_kind = "metadata_dataset_id"
        else:
            scope_kind = "open"

        debug: dict[str, Any] = {
            "requested_k": int(requested_k),
            "search_k": int(search_k),
            "fetch_k": int(fetch_k),
            "overfetch_enabled": bool(search_k > requested_k),
            "overfetch_reasons": overfetch_reasons,
            "retrieval_profile": str(self.retrieval_profile or "").strip().lower() or None,
            "rerank_profile": str(getattr(settings, "RERANK_PROFILE", "") or "").strip().lower() or None,
            "hierarchy_family_collapse_enabled": bool(hierarchy_family_collapse_enabled),
            "hierarchy_overfetch_factor": int(hierarchy_overfetch_factor),
            "overfetch_multiplier": int(
                self.retrieval_overfetch_multiplier
                if self.retrieval_overfetch_multiplier is not None
                else getattr(settings, "RETRIEVAL_OVERFETCH_MULTIPLIER", 1) or 1
            ),
            "overfetch_cap_k": int(
                self.retrieval_overfetch_max_k
                if self.retrieval_overfetch_max_k is not None
                else getattr(settings, "RETRIEVAL_OVERFETCH_MAX_K", 0) or 0
            ),
            "query_normalization": {
                "original": original_query,
                "normalized": query,
                "applied_rules": list(query_norm.applied_rules or []),
            },
            "scope": {
                "tenant_id": str(self.tenant_id or ""),
                "account_id_present": bool((self.account_id or "").strip()),
                "dataset_id": str(self.dataset_id or ""),
                "dataset_ids_count": len(dataset_scope_ids),
                "document_ids_count": len(self.document_ids or []),
                "kind": scope_kind,
            },
        }
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
        try:
            max_doc_ids = int(getattr(settings, "MILVUS_EXPR_MAX_DOC_IDS", 0) or 0)
            debug["milvus_doc_id_pushdown_skipped"] = bool(
                settings.VECTOR_BACKEND == "milvus"
                and max_doc_ids > 0
                and self.document_ids
                and len(self.document_ids) > max_doc_ids
            )
            debug["milvus_expr_max_doc_ids"] = int(max_doc_ids)
        except (TypeError, ValueError, AttributeError):
            debug["milvus_doc_id_pushdown_skipped"] = None

        embedding_runtime = self._resolve_embedding_runtime(tenant_id=self.tenant_id)
        results = self._hybrid_search(
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
        debug["hybrid_results"] = len(results or [])
        try:
            debug["channels"] = dict(self._last_channel_metrics or {})
        except (TypeError, ValueError, AttributeError):
            debug["channels"] = {}
        channels_debug = debug["channels"] if isinstance(debug.get("channels"), dict) else {}
        debug["retrieval_degraded"] = bool(channels_debug.get("retrieval_degraded", False))
        debug["retrieval_degraded_reasons"] = list(channels_debug.get("degraded_reasons") or [])
        debug["all_retrieval_channels_failed"] = bool(
            channels_debug.get("all_retrieval_channels_failed", False)
        )
        try:
            ch = debug.get("channels") or {}
            timing0 = ch.get("timing") if isinstance(ch, dict) else None
            counts0 = ch.get("counts") if isinstance(ch, dict) else None
            timing_src = timing0 if isinstance(timing0, dict) else {}
            counts_src = counts0 if isinstance(counts0, dict) else {}
            debug["timing"] = {
                "vector_ms": float(timing_src.get("vector_ms") or 0.0),
                "bm25_ms": float(timing_src.get("bm25_ms") or 0.0),
                "lexical_ms": float(timing_src.get("lexical_ms") or 0.0),
                "fusion_ms": float(timing_src.get("fusion_ms") or 0.0),
            }
            debug["counts"] = {
                "vector_candidates": int(counts_src.get("vector_candidates") or 0),
                "bm25_candidates": int(counts_src.get("bm25_candidates") or 0),
            }
        except (TypeError, ValueError, AttributeError):
            debug["timing"] = {"vector_ms": 0.0, "bm25_ms": 0.0, "lexical_ms": 0.0, "fusion_ms": 0.0}
            debug["counts"] = {"vector_candidates": 0, "bm25_candidates": 0}
        # Diversity caps meta is computed inside `_hybrid_search` / `_apply_document_diversity`.
        # Keep it as a small numeric-only object for downstream diagnostics (PII-safe).
        try:
            div = dict(self._last_diversity_caps or {})
            if div:
                debug["diversity"] = div
        except Exception as exc:
            logger.debug(NON_CRITICAL_RETRIEVER_FALLBACK_LOG, exc)
        enrich1: dict[str, Any] = {}
        try:
            results = self._enrich_results_with_db_metadata(
                results,
                stats=enrich1,
                metadata_filter_override=effective_metadata_filter,
                embedding_runtime=embedding_runtime,
            )
        except TypeError as exc:
            message = str(exc)
            if "metadata_filter_override" not in message and "embedding_runtime" not in message:
                raise
            results = self._enrich_results_with_db_metadata(results, stats=enrich1)
        debug["enrich_pass1"] = enrich1
        n_enrich1 = len(results or [])
        try:
            late_filter_dropped = max(0, int(debug.get("hybrid_results") or 0) - int(n_enrich1 or 0))
            debug["late_filter_collapse"] = {
                "before": int(debug.get("hybrid_results") or 0),
                "after": int(n_enrich1 or 0),
                "dropped": int(late_filter_dropped),
                "ratio": round(
                    float(late_filter_dropped) / float(max(1, int(debug.get("hybrid_results") or 0))),
                    6,
                ),
                "filtered_acl": int(enrich1.get("filtered_acl") or 0),
                "filtered_dataset": int(enrich1.get("filtered_dataset") or 0),
                "filtered_not_ready": int(enrich1.get("filtered_not_ready") or 0),
                "filtered_pipeline_version": int(enrich1.get("filtered_pipeline_version") or 0),
                "filtered_metadata_filter": int(enrich1.get("filtered_metadata_filter") or 0),
                "filtered_embedding_space": int(enrich1.get("filtered_embedding_space") or 0),
                "filtered_orphaned": int(enrich1.get("filtered_orphaned") or 0),
            }
        except Exception as exc:
            logger.debug(NON_CRITICAL_RETRIEVER_FALLBACK_LOG, exc)
        enriched_result_keys = {self._result_key(item) for item in results if isinstance(item, dict)}

        results = self._expand_results_with_neighbors(results)
        debug["neighbors_delta"] = len(results or []) - n_enrich1

        n_neighbors = len(results or [])
        results = self._auto_merge_parent_child(results)
        debug["parent_child_merge_delta"] = len(results or []) - n_neighbors
        enrich2: dict[str, Any] = {}
        expanded_result_keys = {self._result_key(item) for item in results if isinstance(item, dict)}
        if expanded_result_keys != enriched_result_keys:
            # New identities must pass ACL/version/embedding-space checks before exposure.
            try:
                results = self._enrich_results_with_db_metadata(
                    results,
                    stats=enrich2,
                    metadata_filter_override=effective_metadata_filter,
                    embedding_runtime=embedding_runtime,
                )
            except TypeError as exc:
                message = str(exc)
                if "metadata_filter_override" not in message and "embedding_runtime" not in message:
                    raise
                results = self._enrich_results_with_db_metadata(results, stats=enrich2)
        debug["enrich_pass2"] = enrich2

        exact_anchor_post_stats: dict[str, Any] = {}
        results = self._apply_metadata_exact_anchor_post_ordering(
            query,
            results,
            stats=exact_anchor_post_stats,
        )
        if exact_anchor_post_stats:
            debug["metadata_exact_anchor_post"] = exact_anchor_post_stats

        # Optional: lifecycle governance-aware retrieval policy (disabled by default).
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
        stitch_enabled = bool(getattr(settings, "RAG_CONTEXT_STITCHING_ENABLED", False))
        debug["stitching_enabled"] = stitch_enabled
        prefix = list(results[:requested_k]) if results else []
        if stitch_enabled and prefix:
            try:
                prefix = self._stitch_results_for_continuity(prefix)
            except Exception as exc:
                logger.debug(NON_CRITICAL_RETRIEVER_FALLBACK_LOG, exc)

        docs: list[Document] = []
        for r in prefix:
            meta = dict(r.get("metadata") or {})
            meta.pop(_RETRIEVAL_EXPECTED_EMBEDDING_SPACE_KEY, None)
            meta["score"] = r.get("score")
            meta["vector_score"] = r.get("vector_score")
            meta["bm25_score"] = r.get("bm25_score")
            if "lexical_score" in r:
                meta["lexical_score"] = r.get("lexical_score")
            if "sparse_score" in r:
                meta["sparse_score"] = r.get("sparse_score")
            if "field_aware_signal" in r:
                meta["field_aware_signal"] = r.get("field_aware_signal")
            if "field_aware_boost" in r:
                meta["field_aware_boost"] = r.get("field_aware_boost")
            if "chunk_type_signal" in r:
                meta["chunk_type_signal"] = r.get("chunk_type_signal")
            if "chunk_type_boost" in r:
                meta["chunk_type_boost"] = r.get("chunk_type_boost")
            if "keyword_score" in r:
                meta["keyword_score"] = r.get("keyword_score")
            for key in (
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
            ):
                if key in r:
                    meta[key] = r.get(key)
            if "rerank_score" in r:
                meta["rerank_score"] = r.get("rerank_score")
            if "retrieval_score" in r:
                meta["retrieval_score"] = r.get("retrieval_score")
            if "reranker_provider" in r:
                meta["reranker_provider"] = r.get("reranker_provider")
            if "rerank_elapsed_sec" in r:
                meta["rerank_elapsed_sec"] = r.get("rerank_elapsed_sec")
            if "rerank_model_used" in r:
                meta["rerank_model_used"] = r.get("rerank_model_used")
            docs.append(Document(page_content=r.get("content", ""), metadata=meta, id=r.get("chunk_id")))
        debug["final_docs"] = len(docs)
        self._last_debug_metrics = debug
        return docs

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

        prefer_authority = bool(getattr(settings, "RETRIEVAL_GOVERNANCE_PREFER_AUTHORITY", False))
        prefer_latest = bool(getattr(settings, "RETRIEVAL_GOVERNANCE_PREFER_LATEST", False))
        filter_superseded = bool(getattr(settings, "RETRIEVAL_GOVERNANCE_FILTER_SUPERSEDED", False))

        enabled = bool(prefer_authority or prefer_latest or filter_superseded)
        if stats is not None:
            stats["enabled"] = bool(enabled)
            stats["prefer_authority"] = bool(prefer_authority)
            stats["prefer_latest"] = bool(prefer_latest)
            stats["filter_superseded"] = bool(filter_superseded)
            stats["feature_source"] = "candidate_metadata"
            stats["db_roundtrips"] = 0

        if not enabled:
            return results

        if stats is not None:
            stats["input_results"] = len(results)

        doc_features: dict[str, dict[str, Any]] = {}
        superseded_doc_ids: set[str] = set()
        unpublished_doc_ids: set[str] = set()
        for result in results:
            did = self._get_doc_id(result)
            if not did:
                continue
            meta = result.get("metadata") if isinstance(result, dict) else None
            meta = meta if isinstance(meta, dict) else {}
            try:
                authority = int(meta.get("_governance_authority_level", meta.get("authority_level", 0)) or 0)
            except (TypeError, ValueError, AttributeError):
                authority = 0
            try:
                updated_ts = float(meta.get("_governance_updated_ts", meta.get("updated_ts")))
            except (TypeError, ValueError, AttributeError):
                updated_ts = None

            publication_status = str(
                meta.get("_governance_publication_status", meta.get("publication_status", "published"))
                or "published"
            ).strip().lower()
            supersedes_id = str(
                meta.get("_governance_supersedes_document_id", meta.get("supersedes_document_id", "")) or ""
            ).strip()

            doc_features[did] = {
                "authority_level": max(0, min(100, authority)),
                "updated_ts": updated_ts,
                "publication_status": publication_status,
            }
            if publication_status != "published":
                unpublished_doc_ids.add(did)
            if filter_superseded and publication_status == "published" and supersedes_id:
                superseded_doc_ids.add(supersedes_id)

        if stats is not None:
            stats["candidate_docs"] = len(doc_features)

        out = list(results)

        filtered_unpublished = 0
        if unpublished_doc_ids:
            before = len(out)
            out = [r for r in out if self._get_doc_id(r) not in unpublished_doc_ids]
            filtered_unpublished = max(0, before - len(out))

        filtered_superseded = 0
        if filter_superseded and superseded_doc_ids:
            before = len(out)
            out = [r for r in out if self._get_doc_id(r) not in superseded_doc_ids]
            filtered_superseded = max(0, before - len(out))

        reordered = False
        avg_boost = 0.0
        max_boost = 0.0

        if (prefer_authority or prefer_latest) and out:
            auth_boost_max = float(getattr(settings, "RETRIEVAL_GOVERNANCE_AUTHORITY_BOOST_MAX", 0.0) or 0.0)
            latest_boost_max = float(getattr(settings, "RETRIEVAL_GOVERNANCE_LATEST_BOOST_MAX", 0.0) or 0.0)
            window_days = max(1, int(getattr(settings, "RETRIEVAL_GOVERNANCE_LATEST_WINDOW_DAYS", 180) or 180))

            now_ts = time.time()
            boosts: list[float] = []
            scored: list[tuple[float, int, dict[str, Any]]] = []
            for i, r in enumerate(out):
                try:
                    base = float(r.get("score") or r.get("retrieval_score") or 0.0)
                except (TypeError, ValueError, AttributeError):
                    base = 0.0
                did = self._get_doc_id(r)
                feats = doc_features.get(did) if did else None
                feats = feats if isinstance(feats, dict) else {}

                boost = 0.0
                if prefer_authority and auth_boost_max > 0.0:
                    try:
                        auth = int(feats.get("authority_level") or 0)
                    except (TypeError, ValueError, AttributeError):
                        auth = 0
                    auth = max(0, min(100, auth))
                    boost += (float(auth) / 100.0) * auth_boost_max

                if prefer_latest and latest_boost_max > 0.0:
                    ts_sec = feats.get("updated_ts")
                    try:
                        ts_sec_f = float(ts_sec) if ts_sec is not None else None
                    except (TypeError, ValueError, AttributeError):
                        ts_sec_f = None
                    if ts_sec_f is not None and ts_sec_f > 0:
                        age_days = max(0.0, (now_ts - ts_sec_f) / 86400.0)
                        recency = max(0.0, 1.0 - (age_days / float(window_days)))
                        boost += recency * latest_boost_max

                comp = base + boost
                boosts.append(boost)
                scored.append((comp, i, r))

            scored_sorted = sorted(scored, key=lambda x: (-x[0], x[1]))
            out_sorted = [r for _score, _i, r in scored_sorted]
            reordered = out_sorted != out
            out = out_sorted

            if boosts:
                try:
                    avg_boost = float(sum(boosts)) / float(len(boosts))
                except Exception as exc:
                    _log_retriever_fallback('_apply_governance_policy', exc)
                    avg_boost = 0.0
                try:
                    max_boost = float(max(boosts))
                except (TypeError, ValueError, AttributeError):
                    max_boost = 0.0

        if stats is not None:
            stats["filtered_unpublished"] = int(filtered_unpublished)
            stats["filtered_superseded"] = int(filtered_superseded)
            stats["output_results"] = len(out)
            stats["reordered"] = bool(reordered)
            # Keep numeric-only summary for downstream debugging/observability.
            stats["avg_boost"] = round(float(avg_boost), 6)
            stats["max_boost"] = round(float(max_boost), 6)

        return out

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

    def _compact_high_confidence_results(
        self,
        results: list[dict[str, Any]],
        *,
        top_k: int,
        stats: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        limited = list(results or [])[: max(1, int(top_k or 1))]
        policy_config: dict[str, Any] = {"enabled": False}
        policy_plugin_ref = ""
        for result in limited:
            plugin_ref = self._result_plugin_ref(result)
            if not plugin_ref:
                continue
            candidate_config = retrieval_policy_response_compaction(self._retrieval_policy_for_plugin_ref(plugin_ref))
            if candidate_config.get("enabled") is True:
                policy_config = candidate_config
                policy_plugin_ref = plugin_ref
                break

        enabled = bool(
            getattr(settings, "RETRIEVAL_COMPACT_HIGH_CONFIDENCE_ENABLED", False)
            or policy_config.get("enabled") is True
        )
        if stats is not None:
            stats.clear()
            stats["enabled"] = bool(enabled)
            stats["before"] = int(len(limited))
            stats["after"] = int(len(limited))
            stats["dropped"] = 0
            stats["source"] = "policy" if policy_config.get("enabled") is True else "settings"
            if policy_plugin_ref:
                stats["plugin_ref"] = policy_plugin_ref
        if not limited or not enabled:
            return limited

        min_top_score = float(
            policy_config.get("min_top_score", getattr(settings, "RETRIEVAL_COMPACT_MIN_TOP_SCORE", 0.8)) or 0.8
        )
        relative_score_floor = float(
            policy_config.get(
                "relative_score_floor",
                getattr(settings, "RETRIEVAL_COMPACT_RELATIVE_SCORE_FLOOR", 0.65),
            )
            or 0.65
        )
        min_records = int(
            policy_config.get("min_records", getattr(settings, "RETRIEVAL_COMPACT_MIN_RECORDS", 1)) or 1
        )
        compacted = list(
            compact_high_confidence_items(
                limited,
                scores=[_float_or_default(item.get("score"), 0.0) for item in limited],
                top_k=top_k,
                enabled=True,
                min_top_score=min_top_score,
                relative_score_floor=relative_score_floor,
                min_items=min_records,
            )
        )
        if stats is not None:
            stats["after"] = int(len(compacted))
            stats["dropped"] = int(max(0, len(limited) - len(compacted)))
            stats["min_top_score"] = float(min_top_score)
            stats["relative_score_floor"] = float(relative_score_floor)
            stats["min_records"] = int(min_records)
        return compacted

    @staticmethod
    def _result_metadata_layers(result: dict[str, Any]) -> list[dict[str, Any]]:
        meta = result.get("metadata")
        if not isinstance(meta, dict):
            return []
        layers = [meta]
        for key in _PLATFORM_METADATA_VIEW_KEYS:
            nested = meta.get(key)
            if isinstance(nested, dict) and nested:
                layers.append(nested)
        return layers

    @staticmethod
    def _result_plugin_ref(result: dict[str, Any]) -> str:
        for metadata in HybridRetriever._result_metadata_layers(result):
            for key in _PIPELINE_PLUGIN_METADATA_KEYS:
                value = str(metadata.get(key) or "").strip()
                if value:
                    return value
        return ""

    @staticmethod
    @lru_cache(maxsize=128)
    def _retrieval_policy_for_plugin_ref(plugin_ref: str) -> dict[str, Any]:
        ref = str(plugin_ref or "").strip()
        if not ref.startswith("plugin:"):
            return {}
        try:
            from app.rag.pipeline_plugins.registry import resolve_registered_plugin_descriptor

            descriptor = resolve_registered_plugin_descriptor(ref)
        except Exception as exc:  # noqa: BLE001
            logger.debug(NON_CRITICAL_RETRIEVER_FALLBACK_LOG, exc)
            return {}
        policy = getattr(descriptor, "retrieval_policy", None)
        if isinstance(policy, dict) and policy.get("schema") == "mimirq.retrieval_policy.v1":
            return dict(policy)
        return {}

    def _apply_plugin_retrieval_policy(
        self,
        results: list[dict[str, Any]],
        *,
        query: str | None,
    ) -> list[dict[str, Any]]:
        out = list(results or [])
        query_text = str(query or "").strip()
        if not out or not query_text:
            return out

        phrase_boost_weight = max(
            0.0,
            float(getattr(settings, "RETRIEVAL_EXACT_PHRASE_RERANK_BOOST", 0.35) or 0.0),
        )
        exact_adjusted = 0
        for result in out:
            if _apply_exact_content_bonus_to_result(
                query=query_text,
                result=result,
                phrase_boost_weight=phrase_boost_weight,
            ):
                exact_adjusted += 1

        policy_scores, diagnostics = evaluate_records_retrieval_policy(
            out,
            query=query_text,
            plugin_ref_for_record=self._result_plugin_ref,
            metadata_layers_for_record=self._result_metadata_layers,
            policy_resolver=self._retrieval_policy_for_plugin_ref,
        )
        bonuses: list[float] = []
        adjusted = 0
        for result in out:
            scores = policy_scores.get(id(result))
            bonus = float(scores.total) if scores is not None else 0.0
            if not bonus:
                continue
            current_score = _float_or_default(result.get("score"), 0.0)
            result["retrieval_policy_bonus"] = round(float(bonus), 6)
            result["score"] = float(current_score) + float(bonus)
            adjusted += 1
            bonuses.append(float(bonus))

        if int(diagnostics.get("retrieval_policy_record_count") or 0) > 0 and isinstance(self._last_channel_metrics, dict):
            diagnostics["score_adjusted_record_count"] = int(adjusted)
            diagnostics["max_bonus"] = round(float(max(bonuses) if bonuses else 0.0), 6)
            diagnostics["min_bonus"] = round(float(min(bonuses) if bonuses else 0.0), 6)
            diagnostics["avg_bonus"] = round(float(sum(bonuses) / len(bonuses)) if bonuses else 0.0, 6)
            self._last_channel_metrics["retrieval_policy"] = diagnostics

        if adjusted <= 0 and exact_adjusted <= 0:
            return out
        has_budgeted_prefix = any(item.get("fusion_budgeted_prefix_rank") is not None for item in out)
        if has_budgeted_prefix:
            return sorted(
                out,
                key=lambda item: (
                    0 if item.get("fusion_budgeted_prefix_rank") is not None else 1,
                    -_float_or_default(item.get("score"), 0.0),
                    self._result_key(item),
                ),
            )
        return sorted(out, key=lambda item: (-_float_or_default(item.get("score"), 0.0), self._result_key(item)))


# Global instance
hybrid_retriever = HybridRetriever()

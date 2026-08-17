"""
Hybrid Retriever: Vector retrieval + BM25 + optional MMR diversity reranking.
Reference: RAG_Agent example repository. Retrieval modes and reranking strategies are configurable.
"""

import heapq
import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
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
    _RETRIEVAL_DISPLAY_CONTENT_KEY,
    _RETRIEVAL_EXPECTED_EMBEDDING_SPACE_KEY,
    LEXICAL_DB_SEARCH_FAILED_LOG,
    NON_CRITICAL_RETRIEVER_FALLBACK_LOG,
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
from app.rag.retrieval.retriever_options import (
    HybridSearchOptions,
    _build_retrieval_cache_behavior_hash,
    _dataset_scoped_runtime_lookup_error,
    _metadata_filter_has_dataset_scope,
    _resolve_hybrid_search_options,
)
from app.rag.retrieval.retriever_policy import RetrievalPolicyMixin
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


_CORPUS_TOKEN_LOCAL_CACHE_TTL_SEC = 1.0
_CORPUS_TOKEN_LOCAL_CACHE_MAX_ENTRIES = 128


class HybridRetriever(
    Bm25IndexMixin,
    DedupDiversityMixin,
    FusionMixin,
    LexicalDBMixin,
    PostProcessMixin,
    SparseIndexMixin,
    ColbertIndexMixin,
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
    _corpus_token_cache: "OrderedDict[tuple[str, str, tuple[str, ...], tuple[str, ...]], tuple[float, str]]" = (
        PrivateAttr(default_factory=OrderedDict)
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
            _log_retriever_fallback("_resolve_entity_partition_keys", exc)
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
        shard_runtime = self._runtime_from_dataset_shards(tenant_id=tenant_id, dataset_ids=dataset_ids)
        if shard_runtime is not None:
            return shard_runtime
        if len(dataset_ids) != 1 or tenant_id is None:
            return self._default_embedding_runtime()
        return self._resolve_single_dataset_embedding_runtime(tenant_id=tenant_id, dataset_id=dataset_ids[0])

    @staticmethod
    def _default_embedding_runtime() -> DatasetEmbeddingRuntimeConfig:
        runtime = resolve_dataset_embedding_runtime(None)
        return cast(
            DatasetEmbeddingRuntimeConfig,
            replace(runtime, embedding_space_hash=current_embedding_space_hash()),
        )

    def _runtime_from_dataset_shards(
        self,
        *,
        tenant_id: UUID | None,
        dataset_ids: tuple[UUID, ...],
    ) -> DatasetEmbeddingRuntimeConfig | None:
        if tenant_id is None or not dataset_ids:
            return None
        shards = self._resolve_dataset_runtime_shards(tenant_id=tenant_id, dataset_ids=dataset_ids)
        if len(shards) == 1:
            return shards[0][0]
        if len(shards) > 1:
            return self._default_embedding_runtime()
        return None

    def _resolve_single_dataset_embedding_runtime(
        self,
        *,
        tenant_id: UUID,
        dataset_id: UUID,
    ) -> DatasetEmbeddingRuntimeConfig:
        db = SessionLocal()
        try:
            return self._load_single_dataset_embedding_runtime(db, tenant_id=tenant_id, dataset_id=dataset_id)
        except ValueError:
            raise
        except Exception as exc:
            if isinstance(exc, LookupError):
                raise
            _log_retriever_fallback("_resolve_embedding_runtime", exc)
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

    def _load_single_dataset_embedding_runtime(
        self,
        db: Session,
        *,
        tenant_id: UUID,
        dataset_id: UUID,
    ) -> DatasetEmbeddingRuntimeConfig:
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
        return runtime if runtime.dataset_scoped else self._default_embedding_runtime()

    def _resolve_dataset_runtime_shards(
        self,
        *,
        tenant_id: UUID | None,
        dataset_ids: tuple[UUID, ...] | None = None,
    ) -> list[tuple[DatasetEmbeddingRuntimeConfig, tuple[UUID, ...]]]:
        scope_dataset_ids = self._normalize_dataset_scope_ids(dataset_ids or self._explicit_dataset_scope_ids())
        if tenant_id is None or not scope_dataset_ids:
            return []

        db = SessionLocal()
        try:
            metadata_by_id = self._dataset_runtime_metadata_by_id(
                db,
                tenant_id=tenant_id,
                scope_dataset_ids=scope_dataset_ids,
            )
            missing_dataset_ids = tuple(
                dataset_id for dataset_id in scope_dataset_ids if str(dataset_id) not in metadata_by_id
            )
            if missing_dataset_ids:
                raise _dataset_scoped_runtime_lookup_error(
                    tenant_id=tenant_id,
                    dataset_ids=missing_dataset_ids,
                    reason="unavailable",
                )
            return self._group_dataset_runtime_shards(scope_dataset_ids, metadata_by_id=metadata_by_id)
        except ValueError:
            raise
        except Exception as exc:
            if isinstance(exc, LookupError):
                raise
            _log_retriever_fallback("_resolve_dataset_runtime_shards", exc)
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

    def _dataset_runtime_metadata_by_id(
        self,
        db: Session,
        *,
        tenant_id: UUID,
        scope_dataset_ids: tuple[UUID, ...],
    ) -> dict[str, dict[str, Any]]:
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
        return metadata_by_id

    def _group_dataset_runtime_shards(
        self,
        scope_dataset_ids: tuple[UUID, ...],
        *,
        metadata_by_id: dict[str, dict[str, Any]],
    ) -> list[tuple[DatasetEmbeddingRuntimeConfig, tuple[UUID, ...]]]:
        current_space = current_embedding_space_hash()
        grouped: "OrderedDict[DatasetEmbeddingRuntimeConfig, list[UUID]]" = OrderedDict()
        for dataset_id in scope_dataset_ids:
            runtime = resolve_dataset_embedding_runtime(metadata_by_id.get(str(dataset_id)))
            if not runtime.dataset_scoped:
                runtime = cast(
                    DatasetEmbeddingRuntimeConfig,
                    replace(runtime, embedding_space_hash=current_space),
                )
            grouped.setdefault(runtime, []).append(dataset_id)
        return [(runtime, tuple(group_ids)) for runtime, group_ids in grouped.items()]

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
                    str(sparse_status.get("effective_provider") or self.sparse_provider or "deterministic")
                    .strip()
                    .lower()
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
            _log_retriever_fallback("_resolve_candidate_cache_corpus_token", exc)
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
        state = self._prepare_hybrid_search_state(
            query=query,
            search_options=search_options,
            embedding_runtime=embedding_runtime,
        )
        cached = self._resolve_hybrid_search_cache(state)
        if cached is not None:
            return cached
        self._run_hybrid_search_channels(state)
        self._raise_vector_shard_timeout_if_needed(state)
        merged_results = self._merge_hybrid_search_results(state)
        out = self._finalize_hybrid_search_output(state, merged_results)
        self._persist_hybrid_search_output(state, out)
        return out

    def _prepare_hybrid_search_state(
        self,
        *,
        query: str,
        search_options: HybridSearchOptions,
        embedding_runtime: DatasetEmbeddingRuntimeConfig | None,
    ) -> dict[str, Any]:
        state = self._base_hybrid_search_state(query=query, search_options=search_options)
        self._configure_hybrid_runtime_filters(state, embedding_runtime=embedding_runtime)
        self._configure_hybrid_channel_strategy(state)
        self._configure_hybrid_cache_state(state)
        return state

    def _base_hybrid_search_state(self, *, query: str, search_options: HybridSearchOptions) -> dict[str, Any]:
        cache_enabled = bool(
            getattr(settings, "RETRIEVAL_CANDIDATE_SINGLEFLIGHT_ENABLED", True)
            or getattr(settings, "RETRIEVAL_CANDIDATE_CACHE_ENABLED", False)
            or getattr(settings, "SEMANTIC_CACHE_ENABLED", False)
        )
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
        self._last_diversity_caps = {}
        return {
            "query": query,
            "search_options": search_options,
            "top_k": search_options.top_k,
            "score_threshold": search_options.score_threshold,
            "document_ids": search_options.document_ids,
            "tenant_id": search_options.tenant_id,
            "tenant_uuid": search_options.tenant_id or self.tenant_id,
            "alpha": search_options.alpha,
            "enable_weight_rerank": search_options.enable_weight_rerank,
            "vector_weight": search_options.vector_weight,
            "keyword_weight": search_options.keyword_weight,
            "retrieval_mode": str(search_options.retrieval_mode or "hybrid").lower(),
            "mmr_lambda": search_options.mmr_lambda,
            "mmr_fetch_k_multiplier": search_options.mmr_fetch_k_multiplier,
            "behavior_hash": (
                _build_retrieval_cache_behavior_hash(retriever=self, options=search_options) if cache_enabled else None
            ),
            "requested_k": search_options.requested_k,
            "metadata_filter": search_options.metadata_filter,
            "entity_key": search_options.entity_key,
            "partition_keys": search_options.partition_keys,
            "entity_candidates": search_options.entity_candidates,
            "channel_metrics": channel_metrics,
            "channel_health": RetrievalChannelHealth(),
            "vector_elapsed_ms": 0.0,
            "colbert_elapsed_ms": 0.0,
            "bm25_elapsed_ms": 0.0,
            "lexical_elapsed_ms": 0.0,
            "colbert_used": False,
            "colbert_candidates": 0,
            "metadata_exact_protected_results": [],
            "colpali_results": [],
            "want_colpali": False,
            "colpali_reason": "disabled",
            "vector_results": [],
            "bm25_results": [],
            "lexical_results": [],
            "sparse_results": [],
            "vector_shard_failed": False,
            "vector_shard_admission_timeout": None,
            "lexical_run_reason": "not_run",
            "singleflight_leader": False,
            "distributed_singleflight_lease": None,
            "cache_key": None,
            "cache_hit": False,
            "semantic_cache_hit": False,
            "corpus_cache_token": None,
        }

    def _configure_hybrid_runtime_filters(
        self,
        state: dict[str, Any],
        *,
        embedding_runtime: DatasetEmbeddingRuntimeConfig | None,
    ) -> None:
        full_metadata_filter = (
            state["metadata_filter"] if (state["metadata_filter"] and self.metadata_filter_enabled) else None
        )
        if self.metadata_filter_enabled:
            full_metadata_filter, _entity_routing_meta = self._merge_entity_partition_metadata_filter(
                query=state["query"],
                metadata_filter=full_metadata_filter,
                entity_key=state["entity_key"],
                partition_keys=state["partition_keys"],
                entity_candidates=state["entity_candidates"],
            )
        full_metadata_filter = self._with_dataset_scope_filter(full_metadata_filter)
        dataset_scope_ids = self._explicit_dataset_scope_ids()
        runtime_scope_ids = dataset_scope_ids
        document_scope_resolution_failed = False
        has_unscoped_document_runtime = False
        if not runtime_scope_ids:
            if state["document_ids"]:
                document_scope = self._resolve_document_dataset_scope(
                    tenant_id=state["tenant_uuid"],
                    document_ids=state["document_ids"],
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
            self._resolve_dataset_runtime_shards(tenant_id=state["tenant_uuid"], dataset_ids=runtime_scope_ids)
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
            for runtime, shard_dataset_ids in runtime_shards
            for dataset_id in shard_dataset_ids
            if runtime is not None
        }
        runtime_scope_missing_dataset_ids = tuple(
            dataset_id for dataset_id in runtime_scope_ids if dataset_id not in runtime_shard_dataset_ids
        )
        runtime = embedding_runtime or self._resolve_embedding_runtime(tenant_id=state["tenant_uuid"])
        if len(runtime_shards) == 1:
            runtime = runtime_shards[0][0]
        embedding_space = str(runtime.embedding_space_hash or "").strip()
        bm25_filter = None
        vector_filter = None
        if full_metadata_filter and isinstance(full_metadata_filter, dict):
            bm25_filter = {
                key: value
                for key, value in full_metadata_filter.items()
                if isinstance(key, str) and not str(key).startswith("document_user.")
            }
            vector_filter = self._build_vector_filter(bm25_filter, embedding_space=embedding_space)
        state.update(
            {
                "full_metadata_filter": full_metadata_filter,
                "dataset_scope_ids": dataset_scope_ids,
                "runtime_scope_ids": runtime_scope_ids,
                "document_scope_resolution_failed": document_scope_resolution_failed,
                "runtime_shards": runtime_shards,
                "runtime_scope_missing_dataset_ids": runtime_scope_missing_dataset_ids,
                "embedding_runtime": runtime,
                "embedding_space": embedding_space,
                "bm25_filter": bm25_filter,
                "vector_filter": vector_filter,
            }
        )

    def _configure_hybrid_channel_strategy(self, state: dict[str, Any]) -> None:
        state["colpali_reason"], state["want_colpali"] = self._colpali_strategy(state["query"])
        lexical_db_enabled = bool(getattr(settings, "LEXICAL_DB_ENABLED", True))
        bm25_index_enabled = bool(getattr(settings, "BM25_INDEX_ENABLED", True))
        keyword_bm25_secondary_enabled = bool(getattr(settings, "RETRIEVAL_KEYWORD_BM25_SECONDARY_ENABLED", False))
        retrieval_mode = state["retrieval_mode"]
        want_vector = retrieval_mode in ("hybrid", "vector", "mmr")
        want_bm25 = retrieval_mode in ("hybrid", "keyword", "mmr")
        want_lexical = retrieval_mode in ("hybrid", "keyword", "mmr") and lexical_db_enabled
        want_sparse = retrieval_mode in ("hybrid", "keyword", "mmr") and self._effective_sparse_enabled()
        keyword_strategy = None
        if retrieval_mode == "keyword":
            want_bm25, keyword_strategy = self._keyword_mode_strategy(
                lexical_db_enabled=lexical_db_enabled,
                keyword_bm25_secondary_enabled=keyword_bm25_secondary_enabled,
            )
        if want_bm25 and not bm25_index_enabled:
            want_bm25 = False
            if keyword_strategy is not None:
                keyword_strategy["bm25_index_enabled"] = False
        elif keyword_strategy is not None:
            keyword_strategy["bm25_index_enabled"] = bool(bm25_index_enabled)
        state.update(
            {
                "lexical_db_enabled": lexical_db_enabled,
                "bm25_index_enabled": bm25_index_enabled,
                "want_vector": want_vector,
                "want_bm25": want_bm25,
                "want_lexical": want_lexical,
                "want_sparse": want_sparse,
                "keyword_strategy": keyword_strategy,
                "lexical_hybrid_fallback_only": (
                    bool(self.lexical_db_hybrid_fallback_only)
                    if self.lexical_db_hybrid_fallback_only is not None
                    else bool(getattr(settings, "LEXICAL_DB_HYBRID_FALLBACK_ONLY", True))
                ),
            }
        )

    def _colpali_strategy(self, query: str) -> tuple[str, bool]:
        if not bool(getattr(settings, "COLPALI_RETRIEVAL_ENABLED", False)):
            return "COLPALI_RETRIEVAL_ENABLED=false", False
        try:
            from app.rag.policy.modality_router import classify_query_modality  # noqa: WPS433

            modality, _reasons = classify_query_modality(query)
            if str(modality or "").strip().lower() == "image":
                return "image_query", True
        except Exception as exc:
            _log_retriever_fallback("_hybrid_search", exc)
            return "router_exception", False
        return "disabled", False

    @staticmethod
    def _keyword_mode_strategy(
        *,
        lexical_db_enabled: bool,
        keyword_bm25_secondary_enabled: bool,
    ) -> tuple[bool, dict[str, Any]]:
        if lexical_db_enabled:
            return keyword_bm25_secondary_enabled, {
                "primary": "lexical_db",
                "secondary": "bm25" if keyword_bm25_secondary_enabled else None,
                "bm25_secondary_enabled": bool(keyword_bm25_secondary_enabled),
                "lexical_db_enabled": True,
            }
        return True, {
            "primary": "bm25",
            "secondary": None,
            "bm25_secondary_enabled": False,
            "lexical_db_enabled": False,
            "fallback_reason": "lexical_db_disabled",
        }

    def _configure_hybrid_cache_state(self, state: dict[str, Any]) -> None:
        metadata_filter_dataset_scoped = bool(
            self.metadata_filter_enabled
            and _metadata_filter_has_dataset_scope(
                state["full_metadata_filter"] if isinstance(state["full_metadata_filter"], dict) else None
            )
        )
        cache_scope = prepare_hybrid_cache_scope(
            cache_enabled=bool(getattr(settings, "RETRIEVAL_CANDIDATE_CACHE_ENABLED", False)),
            distributed_singleflight_enabled=bool(getattr(settings, "RETRIEVAL_CANDIDATE_SINGLEFLIGHT_ENABLED", True)),
            semantic_cache_enabled=bool(getattr(settings, "SEMANTIC_CACHE_ENABLED", False)),
            semantic_cache_dataset_scoped=bool(state["embedding_runtime"].dataset_scoped),
            tenant_id=state["tenant_uuid"],
            account_id=self.account_id,
            dataset_scope_ids=state["dataset_scope_ids"],
            document_ids=state["document_ids"],
            metadata_filter_dataset_scoped=metadata_filter_dataset_scoped,
            document_scope_resolution_failed=state["document_scope_resolution_failed"],
            runtime_scope_ids=state["runtime_scope_ids"],
            runtime_shard_count=len(state["runtime_shards"]),
            runtime_scope_missing_dataset_ids=state["runtime_scope_missing_dataset_ids"],
            runtime_pipeline_values=[
                str(runtime.embedding_space_hash or "").strip()
                for runtime, _shard_dataset_ids in state["runtime_shards"]
            ],
            embedding_space=state["embedding_space"] or None,
            cache_ttl=int(getattr(settings, "RETRIEVAL_CANDIDATE_CACHE_TTL_SEC", 0) or 0),
            semantic_cache_ttl=int(getattr(settings, "SEMANTIC_CACHE_TTL_SEC", 0) or 0),
        )
        state.update(
            {
                "cache_scope": cache_scope,
                "account_id0": cache_scope.account_id,
                "dataset_id0": cache_scope.dataset_id,
                "pipeline_key": cache_scope.pipeline_key,
                "doc_ids": cache_scope.document_ids,
                "cache_eligible": cache_scope.cache_eligible,
                "distributed_singleflight_eligible": cache_scope.distributed_singleflight_eligible,
                "semantic_cache_eligible": cache_scope.semantic_cache_eligible,
                "cache_meta": cache_scope.cache_meta,
            }
        )
        if isinstance(self._last_channel_metrics, dict):
            self._last_channel_metrics["cache"] = cache_scope.cache_meta

    def _resolve_hybrid_search_cache(self, state: dict[str, Any]) -> list[dict[str, Any]] | None:
        self._raise_hybrid_scope_failure_if_needed(state)
        self._populate_candidate_corpus_token(state)
        self._lookup_candidate_cache(state)
        cached = self._cached_candidate_payload(state)
        if cached is not None:
            return cached
        self._lookup_semantic_candidate_cache(state)
        semantic_cached = self._cached_semantic_payload(state)
        if semantic_cached is not None:
            return semantic_cached
        return self._acquire_hybrid_singleflight(state)

    def _raise_hybrid_scope_failure_if_needed(self, state: dict[str, Any]) -> None:
        scope_failure_reason = state["cache_scope"].scope_failure_reason
        if scope_failure_reason == "missing_document_runtime":
            exc = _dataset_scoped_runtime_lookup_error(
                tenant_id=state["tenant_uuid"],
                document_ids=state["document_ids"],
                reason="unavailable",
            )
            state["channel_health"].failed("scope", exc)
            state["channel_health"].publish(state["channel_metrics"])
            raise exc
        if scope_failure_reason == "missing_dataset_runtime":
            exc = _dataset_scoped_runtime_lookup_error(
                tenant_id=state["tenant_uuid"],
                dataset_ids=state["runtime_scope_missing_dataset_ids"] or state["runtime_scope_ids"],
                document_ids=state["document_ids"],
                reason="unavailable",
            )
            state["channel_health"].failed("scope", exc)
            state["channel_health"].publish(state["channel_metrics"])
            raise exc

    def _populate_candidate_corpus_token(self, state: dict[str, Any]) -> None:
        if not (
            state["cache_eligible"] or state["distributed_singleflight_eligible"] or state["semantic_cache_eligible"]
        ):
            return
        try:
            state["corpus_cache_token"] = self._resolve_candidate_cache_corpus_token(
                tenant_id=state["tenant_uuid"],
                document_ids=state["document_ids"],
                dataset_ids=state["runtime_scope_ids"],
            )
        except Exception as exc:
            _log_retriever_fallback("_hybrid_search", exc)
            state["corpus_cache_token"] = None
        if state["corpus_cache_token"]:
            return
        if state["cache_eligible"]:
            state["cache_eligible"] = False
            state["cache_meta"]["skip_reason"] = "missing_corpus_cache_token"
        if state["distributed_singleflight_eligible"]:
            state["distributed_singleflight_eligible"] = False
        if state["semantic_cache_eligible"]:
            state["semantic_cache_eligible"] = False
            state["cache_meta"]["semantic"]["skip_reason"] = "missing_corpus_cache_token"
        state["cache_meta"]["enabled"] = bool(state["cache_eligible"])
        state["cache_meta"]["singleflight_enabled"] = bool(state["distributed_singleflight_eligible"])
        state["cache_meta"]["semantic"]["enabled"] = bool(state["semantic_cache_eligible"])

    def _lookup_candidate_cache(self, state: dict[str, Any]) -> None:
        state["cache_meta"]["enabled"] = bool(state["cache_eligible"])
        state["cache_meta"]["singleflight_enabled"] = bool(state["distributed_singleflight_eligible"])
        state["cache_meta"]["semantic"]["enabled"] = bool(state["semantic_cache_eligible"])
        if not (state["cache_eligible"] or state["distributed_singleflight_eligible"]):
            return
        try:
            state["cache_key"] = build_retrieval_candidate_cache_key(
                tenant_id=str(state["tenant_uuid"]),
                account_id=state["account_id0"],
                dataset_id=state["dataset_id0"],
                pipeline_key=state["pipeline_key"],
                corpus_cache_token=state["corpus_cache_token"],
                behavior_hash=state["behavior_hash"],
                query=state["query"],
                top_k=int(state["top_k"] or 0),
                score_threshold=float(state["score_threshold"] or 0.0),
                retrieval_mode=state["retrieval_mode"],
                metadata_filter=state["full_metadata_filter"]
                if isinstance(state["full_metadata_filter"], dict)
                else None,
                document_ids=state["doc_ids"],
            )
            state["cached"] = (
                get_cached_retrieval_candidates(state["cache_key"])
                if (state["cache_eligible"] and state["cache_key"])
                else None
            )
        except Exception as exc:
            _log_retriever_fallback("_hybrid_search", exc)
            state["cached"] = None
            state["cache_eligible"] = False
            state["distributed_singleflight_eligible"] = False
            state["cache_meta"]["skip_reason"] = "lookup_error"

    def _cached_candidate_payload(self, state: dict[str, Any]) -> list[dict[str, Any]] | None:
        if not state.get("cached"):
            return None
        state["cache_hit"] = True
        try:
            if isinstance(self._last_channel_metrics, dict):
                self._last_channel_metrics.setdefault("cache", {})  # type: ignore[call-arg]
                self._last_channel_metrics["cache"]["hit"] = True
                self._last_channel_metrics["cache"].pop("skip_reason", None)
        except Exception as exc:
            logger.debug(NON_CRITICAL_RETRIEVER_FALLBACK_LOG, exc)
        return state["cached"][: state["top_k"]]

    def _lookup_semantic_candidate_cache(self, state: dict[str, Any]) -> None:
        if not (state["semantic_cache_eligible"] and state["corpus_cache_token"]):
            return
        try:
            from app.services.semantic_cache import get_cached_semantic_payload

            state["semantic_cached"], sem_meta = get_cached_semantic_payload(
                tenant_id=str(state["tenant_uuid"]),
                account_id=state["account_id0"],
                dataset_id=state["dataset_id0"],
                corpus_cache_token=str(state["corpus_cache_token"]),
                behavior_hash=state["behavior_hash"],
                query=state["query"],
                top_k=int(state["top_k"] or 0),
                score_threshold=float(state["score_threshold"] or 0.0),
                retrieval_mode=state["retrieval_mode"],
                metadata_filter=state["full_metadata_filter"]
                if isinstance(state["full_metadata_filter"], dict)
                else None,
                document_ids=state["doc_ids"],
            )
            if isinstance(sem_meta, dict):
                state["cache_meta"]["semantic"].update(sem_meta)
        except Exception as exc:
            _log_retriever_fallback("_hybrid_search", exc)
            state["semantic_cached"] = None
            state["cache_meta"]["semantic"]["skip_reason"] = "lookup_error"

    def _cached_semantic_payload(self, state: dict[str, Any]) -> list[dict[str, Any]] | None:
        if not state.get("semantic_cached"):
            return None
        state["semantic_cache_hit"] = True
        try:
            if isinstance(self._last_channel_metrics, dict):
                self._last_channel_metrics.setdefault("cache", {})  # type: ignore[call-arg]
                self._last_channel_metrics["cache"]["semantic"]["hit"] = True
                self._last_channel_metrics["cache"]["semantic"].pop("skip_reason", None)
        except Exception as exc:
            logger.debug(NON_CRITICAL_RETRIEVER_FALLBACK_LOG, exc)
        return state["semantic_cached"][: state["top_k"]]

    def _acquire_hybrid_singleflight(self, state: dict[str, Any]) -> list[dict[str, Any]] | None:
        if not (state["distributed_singleflight_eligible"] and state["cache_key"] and not state["cache_hit"]):
            return None
        local_singleflight_leader = False
        try:
            state["singleflight_leader"], inflight_future = acquire_inflight_retrieval_candidates(state["cache_key"])
            local_singleflight_leader = bool(state["singleflight_leader"])
            if not state["singleflight_leader"]:
                follower = self._wait_for_local_singleflight(state, inflight_future)
                if follower is not None:
                    return follower
            state["cache_meta"]["singleflight_role"] = "leader"
            follower = self._wait_for_distributed_singleflight(state)
            if follower is not None:
                return follower
        except RetrievalCandidateSingleflightTimeoutError:
            raise
        except Exception as exc:
            _log_retriever_fallback("_hybrid_search", exc)
            state["singleflight_leader"] = local_singleflight_leader
            state["distributed_singleflight_lease"] = None
        return None

    def _wait_for_local_singleflight(self, state: dict[str, Any], inflight_future: Any) -> list[dict[str, Any]] | None:
        wait_started_at = time.perf_counter()
        try:
            shared_payload = wait_for_inflight_retrieval_candidates(
                state["cache_key"],
                inflight_future,
                timeout_sec=max(
                    1.0,
                    float(getattr(settings, "RETRIEVAL_CANDIDATE_SINGLEFLIGHT_WAIT_TIMEOUT_SEC", 60.0) or 60.0),
                ),
            )
        finally:
            state["cache_meta"]["local_singleflight_wait_ms"] = round(
                max(0.0, (time.perf_counter() - wait_started_at) * 1000.0),
                1,
            )
        if isinstance(shared_payload, list):
            state["cache_meta"]["singleflight_hit"] = True
            state["cache_meta"]["singleflight_role"] = "follower"
            return shared_payload[: state["top_k"]]
        return None

    def _wait_for_distributed_singleflight(self, state: dict[str, Any]) -> list[dict[str, Any]] | None:
        distributed_wait_started_at = time.perf_counter()
        try:
            distributed_leader, distributed_payload, state["distributed_singleflight_lease"] = (
                acquire_or_wait_for_distributed_inflight_retrieval_candidates(state["cache_key"])
            )
        finally:
            state["cache_meta"]["distributed_singleflight_wait_ms"] = round(
                max(0.0, (time.perf_counter() - distributed_wait_started_at) * 1000.0),
                1,
            )
        if distributed_leader:
            return None
        if isinstance(distributed_payload, list):
            state["cache_meta"]["singleflight_hit"] = True
            state["cache_meta"]["singleflight_role"] = "follower"
            state["cache_meta"]["distributed_singleflight_hit"] = True
            resolve_inflight_retrieval_candidates(state["cache_key"], distributed_payload)
            return distributed_payload[: state["top_k"]]
        state["singleflight_leader"] = False
        return None

    def _run_hybrid_search_channels(self, state: dict[str, Any]) -> None:
        emit_stream_event("event", {"message": "正在召回候选…"}, dedupe_key="retrieval.recall")
        state["fetch_k"] = self._hybrid_fetch_k(state)
        self._run_vector_channel_for_state(state)
        self._run_keyword_channels_for_state(state)
        self._run_sparse_and_colpali_channels_for_state(state)
        self._run_single_mode_fallback_channels_for_state(state)
        state["channel_health"].publish(state["channel_metrics"])

    def _hybrid_fetch_k(self, state: dict[str, Any]) -> int:
        fetch_k = state["top_k"] * 2
        if state["retrieval_mode"] == "mmr":
            fetch_k = state["top_k"] * max(1, state["mmr_fetch_k_multiplier"])
        return fetch_k

    def _run_vector_channel_for_state(self, state: dict[str, Any]) -> None:
        if not state["want_vector"]:
            return
        self._run_vector_primary_search(state)
        self._run_colbert_fallback_if_needed(state)

    def _run_vector_primary_search(self, state: dict[str, Any]) -> None:
        vector_store = get_vector_store()
        state["channel_health"].started("vector")
        try:
            t0 = time.perf_counter()
            try:
                state["vector_results"] = self._vector_results_for_state(state, vector_store=vector_store)
            finally:
                state["vector_elapsed_ms"] += (time.perf_counter() - t0) * 1000
        except Exception as exc:
            state["channel_health"].failed("vector", exc)
            logger.warning("Vector search failed: %s", exc)
            state["vector_results"] = []

    def _vector_results_for_state(self, state: dict[str, Any], *, vector_store: Any) -> list[dict[str, Any]]:
        if state["runtime_scope_ids"] and not state["runtime_shards"]:
            state["channel_health"].failed("vector", LookupError("MissingDatasetRuntime"))
            return []
        if state["runtime_shards"]:
            return self._vector_results_from_runtime_shards(state, vector_store=vector_store)
        if state["embedding_runtime"].dataset_scoped:
            return self._vector_results_from_dataset_runtime(state)
        results = self._vector_results_from_store_search(state, vector_store=vector_store)
        state["channel_health"].succeeded("vector")
        return results

    def _vector_results_from_runtime_shards(self, state: dict[str, Any], *, vector_store: Any) -> list[dict[str, Any]]:
        vector_results, shard_failures = self._search_vector_runtime_shards(
            query=state["query"],
            top_k=state["fetch_k"],
            score_threshold=state["score_threshold"],
            document_ids=state["document_ids"],
            tenant_id=state["tenant_uuid"],
            metadata_filter=state["bm25_filter"],
            runtime_shards=state["runtime_shards"],
            vector_store=vector_store,
        )
        for exc in shard_failures:
            state["channel_health"].failed("vector", exc)
            if state["vector_shard_admission_timeout"] is None and isinstance(exc, RetrievalAdmissionTimeoutError):
                state["vector_shard_admission_timeout"] = exc
        state["vector_shard_failed"] = bool(shard_failures)
        if state["runtime_scope_missing_dataset_ids"]:
            state["channel_health"].failed("vector", LookupError("MissingDatasetRuntime"))
            state["vector_shard_failed"] = True
        if len(shard_failures) < len(state["runtime_shards"]):
            state["channel_health"].succeeded("vector")
        return vector_results

    def _vector_results_from_dataset_runtime(self, state: dict[str, Any]) -> list[dict[str, Any]]:
        vector_results = self._search_dataset_scoped_vectors(
            query=state["query"],
            top_k=state["fetch_k"],
            score_threshold=state["score_threshold"],
            document_ids=state["document_ids"],
            tenant_id=state["tenant_uuid"],
            metadata_filter=state["vector_filter"],
            embedding_runtime=state["embedding_runtime"],
        )
        return self._tag_vector_hits_with_expected_space(
            vector_results,
            expected_space=str(state["embedding_runtime"].embedding_space_hash or "").strip(),
        )

    def _vector_results_from_store_search(self, state: dict[str, Any], *, vector_store: Any) -> list[dict[str, Any]]:
        search_kwargs = {
            "query": state["query"],
            "top_k": state["fetch_k"],
            "score_threshold": state["score_threshold"],
            "document_ids": state["document_ids"],
            "tenant_id": state["tenant_uuid"],
        }
        if state["vector_filter"]:
            search_kwargs["metadata_filter"] = state["vector_filter"]
        return vector_store.search(**search_kwargs)

    def _run_colbert_fallback_if_needed(self, state: dict[str, Any]) -> None:
        if state["vector_results"] or not bool(getattr(settings, "COLBERT_RETRIEVAL_ENABLED", False)):
            return
        state["channel_health"].started("colbert")
        try:
            t0 = time.perf_counter()
            try:
                state["vector_results"] = self._search_colbert_ann(
                    query=state["query"],
                    top_k=state["fetch_k"],
                    document_ids=state["document_ids"],
                    tenant_id=state["tenant_uuid"],
                    metadata_filter=state["bm25_filter"],
                )
                state["colbert_used"] = True
                state["colbert_candidates"] = int(len(state["vector_results"] or []))
                state["channel_health"].succeeded("colbert")
            finally:
                delta_ms = (time.perf_counter() - t0) * 1000
                state["vector_elapsed_ms"] += delta_ms
                state["colbert_elapsed_ms"] += delta_ms
        except Exception as exc:
            state["channel_health"].failed("colbert", exc)
            logger.warning("ColBERT ANN search failed: %s", exc)
            state["vector_results"] = []

    def _run_keyword_channels_for_state(self, state: dict[str, Any]) -> None:
        if state["retrieval_mode"] == "keyword":
            self._run_keyword_mode_channels(state)
            return
        self._run_hybrid_keyword_channels(state)

    def _run_keyword_mode_channels(self, state: dict[str, Any]) -> None:
        if state["want_lexical"]:
            state["lexical_results"] = self._timed_search_channel(
                state,
                channel="lexical_db",
                search_fn=lambda: self._search_lexical_db(
                    query=state["query"],
                    top_k=state["fetch_k"],
                    document_ids=state["document_ids"],
                    tenant_id=state["tenant_uuid"],
                    metadata_filter=state["bm25_filter"],
                ),
                warning_message=LEXICAL_DB_SEARCH_FAILED_LOG,
                timing_key="lexical_elapsed_ms",
                success_reason="keyword_primary",
            )
        if state["want_bm25"] or (not state["lexical_results"] and state["bm25_index_enabled"]):
            state["bm25_results"] = self._timed_search_channel(
                state,
                channel="bm25",
                search_fn=lambda: self._search_bm25(
                    query=state["query"],
                    top_k=state["fetch_k"],
                    document_ids=state["document_ids"],
                    tenant_id=state["tenant_uuid"],
                    metadata_filter=state["bm25_filter"],
                ),
                warning_message="BM25 search failed: %s",
                timing_key="bm25_elapsed_ms",
            )

    def _run_hybrid_keyword_channels(self, state: dict[str, Any]) -> None:
        if state["want_bm25"]:
            state["bm25_results"] = self._timed_search_channel(
                state,
                channel="bm25",
                search_fn=lambda: self._search_bm25(
                    query=state["query"],
                    top_k=state["fetch_k"],
                    document_ids=state["document_ids"],
                    tenant_id=state["tenant_uuid"],
                    metadata_filter=state["bm25_filter"],
                ),
                warning_message="BM25 search failed: %s",
                timing_key="bm25_elapsed_ms",
            )
        self._run_lexical_fallback_channels(state)

    def _timed_search_channel(
        self,
        state: dict[str, Any],
        *,
        channel: str,
        search_fn,
        warning_message: str,
        timing_key: str,
        success_reason: str | None = None,
    ) -> list[dict[str, Any]]:
        state["channel_health"].started(channel)
        t0 = time.perf_counter()
        try:
            results = search_fn()
            state["channel_health"].succeeded(channel)
            if success_reason is not None:
                state["lexical_run_reason"] = success_reason
            return results
        except Exception as exc:
            state["channel_health"].failed(channel, exc)
            logger.warning(warning_message, exc)
            if channel == "lexical_db":
                state["lexical_run_reason"] = "error"
            return []
        finally:
            state[timing_key] += (time.perf_counter() - t0) * 1000

    def _run_lexical_fallback_channels(self, state: dict[str, Any]) -> None:
        primary_candidate_count = len(state["vector_results"] or []) + len(state["bm25_results"] or [])
        metadata_exact_fallback_enabled = (
            bool(self.lexical_db_hybrid_metadata_exact_fallback_enabled)
            if self.lexical_db_hybrid_metadata_exact_fallback_enabled is not None
            else bool(getattr(settings, "LEXICAL_DB_HYBRID_METADATA_EXACT_FALLBACK_ENABLED", True))
        )
        metadata_exact_anchor_like_query = bool(
            metadata_exact_fallback_enabled and _query_looks_like_cjk_metadata_anchor(state["query"])
        )
        primary_has_metadata_exact_anchor = False
        if metadata_exact_anchor_like_query:
            primary_has_metadata_exact_anchor = _results_contain_metadata_exact_anchor(
                state["query"],
                list(state["vector_results"] or []) + list(state["bm25_results"] or []),
                limit=max(1, int(state["top_k"] or 0)),
            )
        metadata_exact_fallback = bool(state["lexical_hybrid_fallback_only"] and metadata_exact_anchor_like_query)
        should_run_lexical = bool(state["want_lexical"]) and (
            not state["lexical_hybrid_fallback_only"]
            or primary_candidate_count < max(1, int(state["top_k"] or 0))
            or metadata_exact_fallback
        )
        if should_run_lexical:
            success_reason = (
                "hybrid_parallel"
                if not state["lexical_hybrid_fallback_only"]
                else ("hybrid_metadata_exact_fallback" if metadata_exact_fallback else "hybrid_fallback")
            )
            state["lexical_results"] = self._timed_search_channel(
                state,
                channel="lexical_db",
                search_fn=lambda: self._search_lexical_db(
                    query=state["query"],
                    top_k=state["fetch_k"],
                    document_ids=state["document_ids"],
                    tenant_id=state["tenant_uuid"],
                    metadata_filter=state["bm25_filter"],
                ),
                warning_message=LEXICAL_DB_SEARCH_FAILED_LOG,
                timing_key="lexical_elapsed_ms",
                success_reason=success_reason,
            )
        elif state["want_lexical"]:
            state["lexical_run_reason"] = "skipped_primary_candidates_sufficient"
        self._run_metadata_exact_db_fallback(
            state, metadata_exact_fallback_enabled, metadata_exact_fallback, primary_has_metadata_exact_anchor
        )

    def _run_metadata_exact_db_fallback(
        self,
        state: dict[str, Any],
        metadata_exact_fallback_enabled: bool,
        metadata_exact_fallback: bool,
        primary_has_metadata_exact_anchor: bool,
    ) -> None:
        metadata_exact_db_results: list[dict[str, Any]] = []
        metadata_exact_db_enabled = (
            bool(self.metadata_exact_db_fallback_enabled)
            if self.metadata_exact_db_fallback_enabled is not None
            else bool(getattr(settings, "RETRIEVAL_METADATA_EXACT_DB_FALLBACK_ENABLED", True))
        )
        metadata_exact_db_reason = "not_run"
        if metadata_exact_db_enabled and metadata_exact_fallback:
            lexical_has_metadata_exact_anchor = _results_contain_metadata_exact_anchor(
                state["query"],
                state["lexical_results"],
                limit=max(1, int(state["top_k"] or 0)),
            )
            t0 = time.perf_counter()
            try:
                metadata_exact_db_results = self._search_metadata_exact_anchor_db(
                    query=state["query"],
                    top_k=state["fetch_k"],
                    document_ids=state["document_ids"],
                    tenant_id=state["tenant_uuid"],
                    metadata_filter=state["bm25_filter"],
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
                state["lexical_elapsed_ms"] += (time.perf_counter() - t0) * 1000
            self._append_metadata_exact_results(state, metadata_exact_db_results)
        elif not metadata_exact_db_enabled:
            metadata_exact_db_reason = "disabled"
        if state["want_lexical"] and isinstance(self._last_channel_metrics, dict):
            self._last_channel_metrics["lexical_metadata_exact_fallback"] = {
                "enabled": bool(metadata_exact_fallback_enabled),
                "query_anchor_like": bool(
                    metadata_exact_fallback_enabled and _query_looks_like_cjk_metadata_anchor(state["query"])
                ),
                "primary_has_exact_anchor": bool(primary_has_metadata_exact_anchor),
                "triggered": bool(metadata_exact_fallback),
            }
            self._last_channel_metrics["metadata_exact_db"] = {
                "enabled": bool(metadata_exact_db_enabled),
                "used": bool(metadata_exact_db_results),
                "candidates": int(len(metadata_exact_db_results or [])),
                "run_reason": metadata_exact_db_reason,
            }

    def _append_metadata_exact_results(
        self, state: dict[str, Any], metadata_exact_db_results: list[dict[str, Any]]
    ) -> None:
        if not metadata_exact_db_results:
            return
        seen_chunk_ids = {
            str((item.get("metadata") or {}).get("chunk_id") or item.get("chunk_id") or "")
            for item in state["lexical_results"]
            if isinstance(item, dict)
        }
        for item in metadata_exact_db_results:
            cid = str((item.get("metadata") or {}).get("chunk_id") or item.get("chunk_id") or "")
            if cid and cid in seen_chunk_ids:
                continue
            if cid:
                seen_chunk_ids.add(cid)
            state["lexical_results"].append(item)
            state["metadata_exact_protected_results"].append(item)

    def _run_sparse_and_colpali_channels_for_state(self, state: dict[str, Any]) -> None:
        self._last_sparse_provider_status = self._resolve_sparse_provider_status(
            sparse_enabled=self._effective_sparse_enabled()
        )
        if not state["want_sparse"]:
            self._last_sparse_provider_status = {
                **(self._last_sparse_provider_status or {}),
                "outcome": "skipped",
                "candidates": 0,
            }
        if state["want_sparse"]:
            state["channel_health"].started("sparse")
            try:
                state["sparse_results"] = self._search_sparse(
                    query=state["query"],
                    top_k=state["fetch_k"],
                    document_ids=state["document_ids"],
                    tenant_id=state["tenant_uuid"],
                    metadata_filter=state["bm25_filter"],
                )
                state["channel_health"].succeeded("sparse")
            except Exception as exc:
                state["channel_health"].failed("sparse", exc)
                logger.warning("Sparse search failed: %s", exc)
                state["sparse_results"] = []
        if state["want_colpali"]:
            state["channel_health"].started("colpali")
            try:
                state["colpali_results"] = self._search_colpali_retriever(
                    query=state["query"],
                    top_k=state["fetch_k"],
                    document_ids=state["document_ids"],
                    tenant_id=state["tenant_uuid"],
                    metadata_filter=state["bm25_filter"],
                )
                state["channel_health"].succeeded("colpali")
            except Exception as exc:
                state["channel_health"].failed("colpali", exc)
                logger.warning("ColPali retriever failed: %s", exc)
                state["colpali_results"] = []

    def _run_single_mode_fallback_channels_for_state(self, state: dict[str, Any]) -> None:
        if state["retrieval_mode"] == "vector" and (not state["vector_results"] or state["vector_shard_failed"]):
            self._run_vector_fallback_channels(state)
        elif (
            state["retrieval_mode"] == "keyword"
            and not state["bm25_results"]
            and not state["lexical_results"]
            and not state["sparse_results"]
        ):
            self._run_keyword_vector_fallback(state)

    def _run_vector_fallback_channels(self, state: dict[str, Any]) -> None:
        state["bm25_results"] = self._timed_search_channel(
            state,
            channel="bm25",
            search_fn=lambda: self._search_bm25(
                query=state["query"],
                top_k=state["fetch_k"],
                document_ids=state["document_ids"],
                tenant_id=state["tenant_uuid"],
                metadata_filter=state["bm25_filter"],
            ),
            warning_message="BM25 search failed: %s",
            timing_key="bm25_elapsed_ms",
        )
        state["lexical_results"] = self._timed_search_channel(
            state,
            channel="lexical_db",
            search_fn=lambda: self._search_lexical_db(
                query=state["query"],
                top_k=state["fetch_k"],
                document_ids=state["document_ids"],
                tenant_id=state["tenant_uuid"],
                metadata_filter=state["bm25_filter"],
            ),
            warning_message=LEXICAL_DB_SEARCH_FAILED_LOG,
            timing_key="lexical_elapsed_ms",
            success_reason="vector_fallback",
        )
        if state["want_sparse"]:
            state["channel_health"].started("sparse")
            try:
                state["sparse_results"] = self._search_sparse(
                    query=state["query"],
                    top_k=state["fetch_k"],
                    document_ids=state["document_ids"],
                    tenant_id=state["tenant_uuid"],
                    metadata_filter=state["bm25_filter"],
                )
                state["channel_health"].succeeded("sparse")
            except Exception as exc:
                state["channel_health"].failed("sparse", exc)
                logger.warning("Sparse search failed: %s", exc)
                state["sparse_results"] = []

    def _run_keyword_vector_fallback(self, state: dict[str, Any]) -> None:
        vector_store = get_vector_store()
        state["channel_health"].started("vector")
        try:
            t0 = time.perf_counter()
            try:
                if state["runtime_scope_ids"] and not state["runtime_shards"]:
                    state["channel_health"].failed("vector", LookupError("MissingDatasetRuntime"))
                    state["vector_results"] = []
                elif state["runtime_shards"]:
                    state["vector_results"], shard_failures = self._search_vector_runtime_shards(
                        query=state["query"],
                        top_k=state["fetch_k"],
                        score_threshold=state["score_threshold"],
                        document_ids=state["document_ids"],
                        tenant_id=state["tenant_uuid"],
                        metadata_filter=state["bm25_filter"],
                        runtime_shards=state["runtime_shards"],
                        vector_store=vector_store,
                    )
                    for exc in shard_failures:
                        state["channel_health"].failed("vector", exc)
                        if state["vector_shard_admission_timeout"] is None and isinstance(
                            exc, RetrievalAdmissionTimeoutError
                        ):
                            state["vector_shard_admission_timeout"] = exc
                    if state["runtime_scope_missing_dataset_ids"]:
                        state["channel_health"].failed("vector", LookupError("MissingDatasetRuntime"))
                    if len(shard_failures) < len(state["runtime_shards"]):
                        state["channel_health"].succeeded("vector")
                elif state["embedding_runtime"].dataset_scoped:
                    state["vector_results"] = self._search_dataset_scoped_vectors(
                        query=state["query"],
                        top_k=state["fetch_k"],
                        score_threshold=state["score_threshold"],
                        document_ids=state["document_ids"],
                        tenant_id=state["tenant_uuid"],
                        metadata_filter=state["vector_filter"],
                        embedding_runtime=state["embedding_runtime"],
                    )
                    state["vector_results"] = self._tag_vector_hits_with_expected_space(
                        state["vector_results"],
                        expected_space=str(state["embedding_runtime"].embedding_space_hash or "").strip(),
                    )
                    state["channel_health"].succeeded("vector")
                else:
                    fallback_kwargs = {
                        "query": state["query"],
                        "top_k": state["fetch_k"],
                        "score_threshold": state["score_threshold"],
                        "document_ids": state["document_ids"],
                        "tenant_id": state["tenant_uuid"],
                    }
                    if state["vector_filter"]:
                        fallback_kwargs["metadata_filter"] = state["vector_filter"]
                    state["vector_results"] = vector_store.search(**fallback_kwargs)
                    state["channel_health"].succeeded("vector")
            finally:
                state["vector_elapsed_ms"] += (time.perf_counter() - t0) * 1000
        except Exception as exc:
            state["channel_health"].failed("vector", exc)
            logger.warning("Vector search failed: %s", exc)
            state["vector_results"] = []

    def _raise_vector_shard_timeout_if_needed(self, state: dict[str, Any]) -> None:
        if not (
            state["vector_shard_admission_timeout"] is not None
            and not state["vector_results"]
            and not state["bm25_results"]
            and not state["lexical_results"]
            and not state["sparse_results"]
            and not state["colpali_results"]
        ):
            return
        if state["singleflight_leader"] and state["cache_key"]:
            reject_current_inflight_retrieval_candidates(state["vector_shard_admission_timeout"])
        release_distributed_inflight_retrieval_candidates(state["distributed_singleflight_lease"])
        raise state["vector_shard_admission_timeout"]

    def _merge_hybrid_search_results(self, state: dict[str, Any]) -> list[dict[str, Any]]:
        self._prepare_channel_results_for_merge(state)
        self._record_channel_diagnostics_from_state(state)
        merged_results = self._merge_results_for_state(state)
        merged_results = self._apply_hybrid_rerank_stack(state, merged_results)
        return self._apply_hybrid_result_postprocessing(state, merged_results)

    def _prepare_channel_results_for_merge(self, state: dict[str, Any]) -> None:
        prepared_channel_results = prepare_hybrid_channel_results(
            query=state["query"],
            vector_results=state["vector_results"],
            bm25_results=state["bm25_results"],
            lexical_results=state["lexical_results"],
            sparse_results=state["sparse_results"],
            document_ids=state["document_ids"],
            vector_filter=state["vector_filter"],
            runtime_shards_present=bool(state["runtime_shards"]),
            chunk_id_lookup=self._chunk_id_lookup.get(self._tenant_key(state["tenant_id"])) or {},
            match_metadata_filter=self._match_metadata_filter,
            metadata_exact_pre_fusion_enabled=bool(
                getattr(settings, "RETRIEVAL_METADATA_EXACT_PRE_FUSION_ENABLED", False)
            ),
            phrase_boost_weight=max(
                0.0,
                float(getattr(settings, "RETRIEVAL_EXACT_PHRASE_RERANK_BOOST", 0.35) or 0.0),
            ),
        )
        state["vector_results"] = prepared_channel_results.vector_results
        state["bm25_results"] = prepared_channel_results.bm25_results
        state["lexical_results"] = prepared_channel_results.lexical_results
        state["sparse_results"] = prepared_channel_results.sparse_results
        state["metadata_exact_pre_fusion_stats"] = prepared_channel_results.metadata_exact_pre_fusion_stats

    def _record_channel_diagnostics_from_state(self, state: dict[str, Any]) -> None:
        try:
            update_hybrid_channel_diagnostics(
                channel_metrics=state["channel_metrics"],
                vector_results=state["vector_results"],
                bm25_results=state["bm25_results"],
                lexical_results=state["lexical_results"],
                sparse_results=state["sparse_results"],
                colpali_results=state["colpali_results"],
                vector_elapsed_ms=state["vector_elapsed_ms"],
                colbert_elapsed_ms=state["colbert_elapsed_ms"],
                bm25_elapsed_ms=state["bm25_elapsed_ms"],
                lexical_elapsed_ms=state["lexical_elapsed_ms"],
                colbert_candidates=state["colbert_candidates"],
                colbert_used=state["colbert_used"],
                colbert_retrieval_enabled=bool(getattr(settings, "COLBERT_RETRIEVAL_ENABLED", False)),
                colbert_provider=str(getattr(settings, "COLBERT_RETRIEVAL_PROVIDER", "") or ""),
                retrieval_mode=state["retrieval_mode"],
                fusion_strategy=str(self.fusion_strategy or ""),
                rrf_k=int(self.rrf_k or 0),
                fusion_weights=(
                    dict(getattr(self, "fusion_weights", None))
                    if isinstance(getattr(self, "fusion_weights", None), dict)
                    else None
                ),
                vector_backend=str(getattr(settings, "VECTOR_BACKEND", "") or ""),
                want_vector=bool(state["want_vector"]),
                want_bm25=bool(state["want_bm25"]),
                want_lexical=bool(state["want_lexical"]),
                want_sparse=bool(state["want_sparse"]),
                want_colpali=bool(state["want_colpali"]),
                vector_filter_applied=bool(state["vector_filter"]),
                bm25_filter_applied=bool(state["bm25_filter"]),
                bm25_index_enabled=bool(state["bm25_index_enabled"]),
                last_bm25_status=dict(self._last_bm25_status or {}),
                lexical_run_reason=state["lexical_run_reason"],
                lexical_hybrid_fallback_only=bool(state["lexical_hybrid_fallback_only"]),
                lexical_db_enabled=bool(state["lexical_db_enabled"]),
                lexical_db_fts_config=str(getattr(settings, "LEXICAL_DB_FTS_CONFIG", "simple") or "simple"),
                lexical_db_trgm_enabled=bool(getattr(settings, "LEXICAL_DB_TRGM_ENABLED", True)),
                lexical_pg_trgm_available=self._lexical_pg_trgm_available,
                metadata_exact_pre_fusion_stats=dict(state["metadata_exact_pre_fusion_stats"]),
                colpali_reason=state["colpali_reason"],
                sparse_provider_status=dict(self._last_sparse_provider_status or {}),
                sparse_provider=self.sparse_provider,
                keyword_strategy=state["keyword_strategy"],
            )
        except Exception:
            try:
                timing = state["channel_metrics"].get("timing")
                if isinstance(timing, dict):
                    timing["vector_ms"] = round(float(state["vector_elapsed_ms"]), 2)
                    timing["colbert_ms"] = round(float(state["colbert_elapsed_ms"]), 2)
                    timing["bm25_ms"] = round(float(state["bm25_elapsed_ms"]), 2)
                    timing["lexical_ms"] = round(float(state["lexical_elapsed_ms"]), 2)
                counts = state["channel_metrics"].get("counts")
                if isinstance(counts, dict):
                    counts["vector_candidates"] = int(len(state["vector_results"] or []))
                    counts["colbert_candidates"] = int(state["colbert_candidates"] or 0)
                    counts["colpali_candidates"] = int(len(state["colpali_results"] or []))
                    counts["bm25_candidates"] = int(len(state["bm25_results"] or []))
                    counts["lexical_candidates"] = int(len(state["lexical_results"] or []))
                    counts["sparse_candidates"] = int(len(state["sparse_results"] or []))
            except Exception as exc:
                logger.debug(NON_CRITICAL_RETRIEVER_FALLBACK_LOG, exc)

    def _merge_results_for_state(self, state: dict[str, Any]) -> list[dict[str, Any]]:
        t_fusion0 = time.perf_counter()
        merged_results = self._merge_results(
            state["vector_results"],
            state["bm25_results"],
            list(state["lexical_results"] or []) + list(state["colpali_results"] or []),
            state["sparse_results"],
            query=state["query"],
            alpha=state["alpha"],
            fusion_strategy=self.fusion_strategy,
            rrf_k=self.rrf_k,
            top_k=state["top_k"],
        )
        merged_results = self._append_protected_metadata_exact_results(merged_results, state, before_diversity=True)
        self._set_channel_metric("merged_pre_dedup", len(merged_results or []))
        exact_anchor_pre_dedup_stats: dict[str, Any] = {}
        merged_results = self._apply_metadata_exact_anchor_post_ordering(
            state["query"],
            merged_results,
            stats=exact_anchor_pre_dedup_stats,
        )
        if exact_anchor_pre_dedup_stats:
            self._set_channel_metric("metadata_exact_pre_dedup_ordering", exact_anchor_pre_dedup_stats)
        merged_results = self._deduplicate_results(merged_results)
        self._set_channel_metric("merged_post_dedup", len(merged_results or []))
        try:
            timing = state["channel_metrics"].get("timing")
            if isinstance(timing, dict):
                timing["fusion_ms"] = round(float((time.perf_counter() - t_fusion0) * 1000), 2)
        except Exception as exc:
            logger.debug(NON_CRITICAL_RETRIEVER_FALLBACK_LOG, exc)
        return merged_results

    def _append_protected_metadata_exact_results(
        self,
        merged_results: list[dict[str, Any]],
        state: dict[str, Any],
        *,
        before_diversity: bool,
    ) -> list[dict[str, Any]]:
        protected_results = state["metadata_exact_protected_results"]
        if not protected_results:
            return merged_results
        merged_keys = {self._result_key(item) for item in merged_results if isinstance(item, dict)}
        protected_added = 0
        for item in protected_results:
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
                metric_key = "protected_added" if before_diversity else "protected_after_diversity_added"
                metadata_exact_meta[metric_key] = int(protected_added)
        return merged_results

    def _set_channel_metric(self, key: str, value: Any) -> None:
        try:
            if isinstance(self._last_channel_metrics, dict):
                self._last_channel_metrics[key] = value
        except Exception as exc:
            logger.debug(NON_CRITICAL_RETRIEVER_FALLBACK_LOG, exc)

    def _apply_hybrid_rerank_stack(
        self,
        state: dict[str, Any],
        merged_results: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if merged_results:
            emit_stream_event("event", {"message": "候选召回完成，正在重排…"}, dedupe_key="retrieval.rerank")
        if state["retrieval_mode"] == "mmr" and merged_results:
            merged_results = self._mmr_rerank(
                merged_results,
                query=state["query"],
                top_k=state["top_k"],
                lambda_mult=state["mmr_lambda"],
            )
        elif state["enable_weight_rerank"] and merged_results:
            merged_results = self._weight_rerank(
                query=state["query"],
                documents=merged_results,
                vector_weight=state["vector_weight"],
                keyword_weight=state["keyword_weight"],
            )
        if merged_results and bool(self.enable_reranker):
            merged_results = self._apply_optional_llm_reranker(state, merged_results)
        return merged_results

    def _apply_optional_llm_reranker(
        self,
        state: dict[str, Any],
        merged_results: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
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
            self._set_channel_metric("rerank", rerank_meta)
            return merged_results
        final_k = max(1, int(state["requested_k"]) if state["requested_k"] is not None else int(state["top_k"] or 0))
        candidates_n = max(int(self.reranker_top_n or settings.RERANKER_TOP_N or 20), final_k)
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
            self._set_channel_metric("rerank", rerank_meta)
            self._set_channel_metric("merged_post_rerank", len(merged_results or []))
            return merged_results
        merged_results = self._run_llm_reranker(
            query=state["query"],
            merged_results=merged_results,
            candidates_n=candidates_n,
            provider=provider,
            rerank_meta=rerank_meta,
        )
        self._set_channel_metric("rerank", rerank_meta)
        return merged_results

    def _run_llm_reranker(
        self,
        *,
        query: str,
        merged_results: list[dict[str, Any]],
        candidates_n: int,
        provider: str,
        rerank_meta: dict[str, Any],
    ) -> list[dict[str, Any]]:
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
            return merged_results
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
            ordered = self._reranked_documents(
                query=query,
                merged_results=merged_results,
                candidates_n=candidates_n,
                id_to_doc=id_to_doc,
                ordered_ids=result.ordered_ids,
                score_map=result.score_map,
                rerank_provider=rerank_provider,
                rerank_elapsed=rerank_elapsed,
                model_used=result.model_used,
                rerank_meta=rerank_meta,
            )
            return ordered + merged_results[candidates_n:]
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
            return merged_results

    def _reranked_documents(
        self,
        *,
        query: str,
        merged_results: list[dict[str, Any]],
        candidates_n: int,
        id_to_doc: dict[str, dict[str, Any]],
        ordered_ids: list[str],
        score_map: dict[str, float],
        rerank_provider: str,
        rerank_elapsed: float,
        model_used: str | None,
        rerank_meta: dict[str, Any],
    ) -> list[dict[str, Any]]:
        ordered: list[dict[str, Any]] = []
        used: set[str] = set()
        boosted_after_rerank = 0
        phrase_boost_weight = max(
            0.0,
            float(getattr(settings, "RETRIEVAL_EXACT_PHRASE_RERANK_BOOST", 0.35) or 0.0),
        )
        for rid in ordered_ids:
            doc = id_to_doc.get(rid)
            if not doc or rid in used:
                continue
            used.add(rid)
            new_doc = dict(doc)
            new_doc["retrieval_score"] = float(new_doc.get("score", 0.0) or 0.0)
            if rid in score_map:
                rerank_score = float(score_map[rid])
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
            new_doc["rerank_model_used"] = model_used
            ordered.append(new_doc)
        if boosted_after_rerank > 0:
            ordered = sorted(ordered, key=lambda item: (-float(item.get("score", 0.0) or 0.0), self._result_key(item)))
            rerank_meta["post_rerank_exact_boosted"] = int(boosted_after_rerank)
        for doc in merged_results[:candidates_n]:
            rid = self._result_key(doc)
            if rid in used:
                continue
            new_doc = dict(doc)
            new_doc.setdefault("reranker_provider", rerank_provider)
            new_doc.setdefault("rerank_elapsed_sec", round(float(rerank_elapsed), 3))
            new_doc.setdefault("rerank_model_used", model_used)
            ordered.append(new_doc)
        return ordered

    def _apply_hybrid_result_postprocessing(
        self,
        state: dict[str, Any],
        merged_results: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        self._set_channel_metric("merged_post_rerank", len(merged_results or []))
        self._set_channel_metric("attribution", self._hybrid_result_attribution(merged_results))
        before_diversity = len(merged_results or [])
        div_caps: dict[str, Any] = {}
        merged_results = self._apply_document_diversity(merged_results, top_k=state["top_k"], stats=div_caps)
        self._last_diversity_caps = div_caps
        merged_results = self._append_protected_metadata_exact_results(merged_results, state, before_diversity=False)
        after_diversity = len(merged_results or [])
        self._set_channel_metric(
            "diversity",
            {
                "before": int(before_diversity),
                "after": int(after_diversity),
                "dropped": int(max(0, before_diversity - after_diversity)),
            },
        )
        self._set_channel_metric("returned_top_k", int(min(int(state["top_k"] or 0), after_diversity)))
        metadata_exact_final_stats: dict[str, Any] = {}
        merged_results = self._apply_metadata_exact_anchor_post_ordering(
            state["query"],
            merged_results,
            stats=metadata_exact_final_stats,
        )
        if metadata_exact_final_stats:
            self._set_channel_metric("metadata_exact_final_ordering", metadata_exact_final_stats)
        return merged_results

    @staticmethod
    def _hybrid_result_attribution(merged_results: list[dict[str, Any]]) -> dict[str, int]:
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
        return attribution

    def _finalize_hybrid_search_output(
        self,
        state: dict[str, Any],
        merged_results: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        out = merged_results[: state["top_k"]]
        cache_store_allowed = not bool(state["channel_metrics"].get("retrieval_degraded", False))
        state["cache_store_allowed"] = cache_store_allowed
        if not cache_store_allowed:
            state["cache_meta"]["store_skip_reason"] = "retrieval_degraded"
            state["cache_meta"]["semantic"]["store_skip_reason"] = "retrieval_degraded"
        return out

    def _persist_hybrid_search_output(self, state: dict[str, Any], out: list[dict[str, Any]]) -> None:
        if (
            state["cache_store_allowed"]
            and state["cache_eligible"]
            and (not state["cache_hit"])
            and state["cache_key"]
            and out
        ):
            try:
                stored = bool(set_cached_retrieval_candidates(state["cache_key"], out))
                if isinstance(self._last_channel_metrics, dict):
                    self._last_channel_metrics.setdefault("cache", {})  # type: ignore[call-arg]
                    self._last_channel_metrics["cache"]["store_ok"] = stored
            except Exception as exc:
                logger.debug(NON_CRITICAL_RETRIEVER_FALLBACK_LOG, exc)
        if state["singleflight_leader"] and state["cache_key"]:
            if state["cache_store_allowed"]:
                publish_distributed_inflight_retrieval_candidates(state["cache_key"], out)
                resolve_inflight_retrieval_candidates(state["cache_key"], out)
            else:
                reject_current_inflight_retrieval_candidates(RuntimeError("retrieval degraded"))
            release_distributed_inflight_retrieval_candidates(state["distributed_singleflight_lease"])
        if (
            state["cache_store_allowed"]
            and state["semantic_cache_eligible"]
            and (not state["semantic_cache_hit"])
            and state["corpus_cache_token"]
            and out
        ):
            try:
                from app.services.semantic_cache import set_cached_semantic_payload

                stored = bool(
                    set_cached_semantic_payload(
                        tenant_id=str(state["tenant_uuid"]),
                        account_id=state["account_id0"],
                        dataset_id=state["dataset_id0"],
                        corpus_cache_token=str(state["corpus_cache_token"]),
                        behavior_hash=state["behavior_hash"],
                        query=state["query"],
                        top_k=int(state["top_k"] or 0),
                        score_threshold=float(state["score_threshold"] or 0.0),
                        retrieval_mode=state["retrieval_mode"],
                        metadata_filter=state["full_metadata_filter"]
                        if isinstance(state["full_metadata_filter"], dict)
                        else None,
                        document_ids=state["doc_ids"],
                        payload=out,
                    )
                )
                if isinstance(self._last_channel_metrics, dict):
                    self._last_channel_metrics.setdefault("cache", {})  # type: ignore[call-arg]
                    self._last_channel_metrics["cache"].setdefault("semantic", {})  # type: ignore[call-arg]
                    self._last_channel_metrics["cache"]["semantic"]["store_ok"] = stored
            except Exception as exc:
                logger.debug(NON_CRITICAL_RETRIEVER_FALLBACK_LOG, exc)

    # ---- LangChain Retriever API ----

    def _get_relevant_documents(
        self,
        query: str,
        *,
        run_manager: CallbackManagerForRetrieverRun,
    ) -> list[Document]:
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
        embedding_runtime = self._resolve_embedding_runtime(tenant_id=self.tenant_id)
        results = self._invoke_hybrid_retrieval(
            query=query,
            embedding_runtime=embedding_runtime,
            effective_metadata_filter=effective_metadata_filter,
            requested_k=requested_k,
            search_k=search_k,
        )
        self._record_hybrid_debug_metrics(debug, results)
        results = self._post_process_retrieval_results(
            query=query,
            results=results,
            debug=debug,
            effective_metadata_filter=effective_metadata_filter,
            embedding_runtime=embedding_runtime,
            requested_k=requested_k,
        )
        docs = self._results_to_documents(results, debug=debug, requested_k=requested_k)
        self._last_debug_metrics = debug
        return docs

    def _normalize_retrieval_query(self, query: str) -> tuple[str, str, Any]:
        max_query_chars = int(getattr(settings, "RETRIEVAL_QUERY_MAX_CHARS", 8_000) or 8_000)
        if len(str(query or "")) > max_query_chars:
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
        if not bool(getattr(settings, "CHAT_ALLOW_OPEN_SCOPE", False)):
            raise ValueError("dataset_id is required when document_ids is empty")
        return metadata_filter_dataset_scoped, dataset_scope_ids

    def _retrieval_search_budget(
        self,
        *,
        dataset_scope_ids: tuple[UUID, ...],
    ) -> tuple[int, int, int, list[str]]:
        requested_k = max(1, int(self.k or 0))
        search_k = requested_k
        if bool(self.enable_reranker):
            search_k = resolve_rerank_search_k(
                requested_k=search_k,
                profile=str(getattr(settings, "RERANK_PROFILE", "") or "").strip().lower() or None,
            )
        hierarchy_family_collapse_enabled = self._should_apply_hierarchy_family_collapse()
        hierarchy_overfetch_factor = max(1, int(self.hierarchy_overfetch_factor or 1))
        if hierarchy_family_collapse_enabled and hierarchy_overfetch_factor > 1:
            search_k = max(search_k, requested_k * hierarchy_overfetch_factor)
        overfetch_reasons = self._retrieval_overfetch_reasons(dataset_scope_ids=dataset_scope_ids)
        if overfetch_reasons:
            search_k = self._apply_retrieval_overfetch_bounds(requested_k=requested_k, search_k=search_k)
        fetch_k = int(search_k) * 2
        if str(self.retrieval_mode or "").strip().lower() == "mmr":
            fetch_k = int(search_k) * max(1, int(self.mmr_fetch_k_multiplier or 0))
        return requested_k, search_k, fetch_k, overfetch_reasons

    def _retrieval_overfetch_reasons(self, *, dataset_scope_ids: tuple[UUID, ...]) -> list[str]:
        if self.document_ids:
            return []
        reasons: list[str] = []
        metadata_filter_requested = bool(
            self.metadata_filter_enabled and isinstance(self.metadata_filter, dict) and self.metadata_filter
        )
        if not dataset_scope_ids and self.tenant_id and (self.account_id or "").strip():
            reasons.append("open_scope_acl")
        if dataset_scope_ids or (self.tenant_id and (self.account_id or "").strip()):
            reasons.append("active_pipeline")
        if metadata_filter_requested:
            reasons.append("metadata_filter")
        return reasons

    def _apply_retrieval_overfetch_bounds(self, *, requested_k: int, search_k: int) -> int:
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
        return search_k

    def _build_retrieval_debug_payload(
        self,
        *,
        original_query: str,
        normalized_query: str,
        query_norm: Any,
        dataset_scope_ids: tuple[UUID, ...],
        metadata_filter_dataset_scoped: bool,
        requested_k: int,
        search_k: int,
        fetch_k: int,
        overfetch_reasons: list[str],
    ) -> dict[str, Any]:
        return {
            "requested_k": int(requested_k),
            "search_k": int(search_k),
            "fetch_k": int(fetch_k),
            "overfetch_enabled": bool(search_k > requested_k),
            "overfetch_reasons": overfetch_reasons,
            "retrieval_profile": str(self.retrieval_profile or "").strip().lower() or None,
            "rerank_profile": str(getattr(settings, "RERANK_PROFILE", "") or "").strip().lower() or None,
            "hierarchy_family_collapse_enabled": bool(self._should_apply_hierarchy_family_collapse()),
            "hierarchy_overfetch_factor": int(max(1, int(self.hierarchy_overfetch_factor or 1))),
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
                "normalized": normalized_query,
                "applied_rules": list(query_norm.applied_rules or []),
            },
            "scope": {
                "tenant_id": str(self.tenant_id or ""),
                "account_id_present": bool((self.account_id or "").strip()),
                "dataset_id": str(self.dataset_id or ""),
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

    def _invoke_hybrid_retrieval(
        self,
        *,
        query: str,
        embedding_runtime: DatasetEmbeddingRuntimeConfig,
        effective_metadata_filter: dict[str, Any] | None,
        requested_k: int,
        search_k: int,
    ) -> list[dict[str, Any]]:
        return self._hybrid_search(
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

    def _record_hybrid_debug_metrics(self, debug: dict[str, Any], results: list[dict[str, Any]]) -> None:
        debug["hybrid_results"] = len(results or [])
        try:
            debug["channels"] = dict(self._last_channel_metrics or {})
        except (TypeError, ValueError, AttributeError):
            debug["channels"] = {}
        channels_debug = debug["channels"] if isinstance(debug.get("channels"), dict) else {}
        debug["retrieval_degraded"] = bool(channels_debug.get("retrieval_degraded", False))
        debug["retrieval_degraded_reasons"] = list(channels_debug.get("degraded_reasons") or [])
        debug["all_retrieval_channels_failed"] = bool(channels_debug.get("all_retrieval_channels_failed", False))
        debug["timing"] = self._safe_retrieval_timing_debug(channels_debug)
        debug["counts"] = self._safe_retrieval_count_debug(channels_debug)
        try:
            diversity = dict(self._last_diversity_caps or {})
            if diversity:
                debug["diversity"] = diversity
        except Exception as exc:
            logger.debug(NON_CRITICAL_RETRIEVER_FALLBACK_LOG, exc)

    @staticmethod
    def _safe_retrieval_timing_debug(channels_debug: dict[str, Any]) -> dict[str, float]:
        try:
            timing_src = channels_debug.get("timing") if isinstance(channels_debug.get("timing"), dict) else {}
            return {
                "vector_ms": float(timing_src.get("vector_ms") or 0.0),
                "bm25_ms": float(timing_src.get("bm25_ms") or 0.0),
                "lexical_ms": float(timing_src.get("lexical_ms") or 0.0),
                "fusion_ms": float(timing_src.get("fusion_ms") or 0.0),
            }
        except (TypeError, ValueError, AttributeError):
            return {"vector_ms": 0.0, "bm25_ms": 0.0, "lexical_ms": 0.0, "fusion_ms": 0.0}

    @staticmethod
    def _safe_retrieval_count_debug(channels_debug: dict[str, Any]) -> dict[str, int]:
        try:
            counts_src = channels_debug.get("counts") if isinstance(channels_debug.get("counts"), dict) else {}
            return {
                "vector_candidates": int(counts_src.get("vector_candidates") or 0),
                "bm25_candidates": int(counts_src.get("bm25_candidates") or 0),
            }
        except (TypeError, ValueError, AttributeError):
            return {"vector_candidates": 0, "bm25_candidates": 0}

    def _post_process_retrieval_results(
        self,
        *,
        query: str,
        results: list[dict[str, Any]],
        debug: dict[str, Any],
        effective_metadata_filter: dict[str, Any] | None,
        embedding_runtime: DatasetEmbeddingRuntimeConfig,
        requested_k: int,
    ) -> list[dict[str, Any]]:
        results, enrich1, enrich_count = self._enrich_retrieval_results(
            results,
            effective_metadata_filter=effective_metadata_filter,
            embedding_runtime=embedding_runtime,
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
    ) -> tuple[list[dict[str, Any]], dict[str, Any], int]:
        enrich_stats: dict[str, Any] = {}
        try:
            results = self._enrich_results_with_db_metadata(
                results,
                stats=enrich_stats,
                metadata_filter_override=effective_metadata_filter,
                embedding_runtime=embedding_runtime,
            )
        except TypeError as exc:
            message = str(exc)
            if "metadata_filter_override" not in message and "embedding_runtime" not in message:
                raise
            results = self._enrich_results_with_db_metadata(results, stats=enrich_stats)
        return results, enrich_stats, len(results or [])

    def _record_late_filter_collapse(
        self,
        debug: dict[str, Any],
        *,
        enrich1: dict[str, Any],
        enrich_count: int,
    ) -> None:
        try:
            late_filter_dropped = max(0, int(debug.get("hybrid_results") or 0) - int(enrich_count or 0))
            debug["late_filter_collapse"] = {
                "before": int(debug.get("hybrid_results") or 0),
                "after": int(enrich_count or 0),
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

    def _reenrich_expanded_results(
        self,
        results: list[dict[str, Any]],
        *,
        enriched_result_keys: set[str],
        effective_metadata_filter: dict[str, Any] | None,
        embedding_runtime: DatasetEmbeddingRuntimeConfig,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        enrich2: dict[str, Any] = {}
        expanded_result_keys = {self._result_key(item) for item in results if isinstance(item, dict)}
        if expanded_result_keys == enriched_result_keys:
            return results, enrich2
        results, enrich2, _count = self._enrich_retrieval_results(
            results,
            effective_metadata_filter=effective_metadata_filter,
            embedding_runtime=embedding_runtime,
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
        results = self._apply_metadata_exact_anchor_post_ordering(
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
        debug["stitching_enabled"] = bool(getattr(settings, "RAG_CONTEXT_STITCHING_ENABLED", False))
        return results

    def _results_to_documents(
        self,
        results: list[dict[str, Any]],
        *,
        debug: dict[str, Any],
        requested_k: int,
    ) -> list[Document]:
        prefix = list(results[:requested_k]) if results else []
        if prefix and bool(getattr(settings, "RAG_CONTEXT_STITCHING_ENABLED", False)):
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
            "sparse_score",
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
                meta[key] = result.get(key)
        return Document(page_content=result.get("content", ""), metadata=meta, id=result.get("chunk_id"))

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

        prefer_authority, prefer_latest, filter_superseded = self._governance_policy_flags()

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

    @staticmethod
    def _governance_policy_flags() -> tuple[bool, bool, bool]:
        return (
            bool(getattr(settings, "RETRIEVAL_GOVERNANCE_PREFER_AUTHORITY", False)),
            bool(getattr(settings, "RETRIEVAL_GOVERNANCE_PREFER_LATEST", False)),
            bool(getattr(settings, "RETRIEVAL_GOVERNANCE_FILTER_SUPERSEDED", False)),
        )

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
            supersedes_id = str(features.get("supersedes_document_id") or "").strip()
            if filter_superseded and features["publication_status"] == "published" and supersedes_id:
                superseded_doc_ids.add(supersedes_id)
        return doc_features, unpublished_doc_ids, superseded_doc_ids

    @staticmethod
    def _governance_features_for_result(result: dict[str, Any]) -> dict[str, Any]:
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
        publication_status = (
            str(meta.get("_governance_publication_status", meta.get("publication_status", "published")) or "published")
            .strip()
            .lower()
        )
        return {
            "authority_level": max(0, min(100, authority)),
            "updated_ts": updated_ts,
            "publication_status": publication_status,
            "supersedes_document_id": str(
                meta.get("_governance_supersedes_document_id", meta.get("supersedes_document_id", "")) or ""
            ).strip(),
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
        return ordered, ordered != results, self._average_boost(boosts), self._max_boost(boosts)

    def _governance_scored_rows(
        self,
        results: list[dict[str, Any]],
        *,
        doc_features: dict[str, dict[str, Any]],
        prefer_authority: bool,
        prefer_latest: bool,
    ) -> tuple[list[tuple[float, int, dict[str, Any]]], list[float]]:
        auth_boost_max = float(getattr(settings, "RETRIEVAL_GOVERNANCE_AUTHORITY_BOOST_MAX", 0.0) or 0.0)
        latest_boost_max = float(getattr(settings, "RETRIEVAL_GOVERNANCE_LATEST_BOOST_MAX", 0.0) or 0.0)
        window_days = max(1, int(getattr(settings, "RETRIEVAL_GOVERNANCE_LATEST_WINDOW_DAYS", 180) or 180))
        now_ts = time.time()
        boosts: list[float] = []
        scored: list[tuple[float, int, dict[str, Any]]] = []
        for index, result in enumerate(results):
            base_score = self._governance_base_score(result)
            doc_id = self._get_doc_id(result)
            features = doc_features.get(doc_id or "", {})
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
        try:
            return float(result.get("score") or result.get("retrieval_score") or 0.0)
        except (TypeError, ValueError, AttributeError):
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
            authority = max(0, min(100, int(features.get("authority_level") or 0)))
            boost += (float(authority) / 100.0) * auth_boost_max
        if prefer_latest and latest_boost_max > 0.0:
            try:
                ts_sec = float(features.get("updated_ts")) if features.get("updated_ts") is not None else None
            except (TypeError, ValueError, AttributeError):
                ts_sec = None
            if ts_sec is not None and ts_sec > 0:
                age_days = max(0.0, (now_ts - ts_sec) / 86400.0)
                recency = max(0.0, 1.0 - (age_days / float(window_days)))
                boost += recency * latest_boost_max
        return boost

    @staticmethod
    def _average_boost(boosts: list[float]) -> float:
        if not boosts:
            return 0.0
        try:
            return float(sum(boosts)) / float(len(boosts))
        except Exception as exc:
            _log_retriever_fallback("_apply_governance_policy", exc)
            return 0.0

    @staticmethod
    def _max_boost(boosts: list[float]) -> float:
        try:
            return float(max(boosts)) if boosts else 0.0
        except (TypeError, ValueError, AttributeError):
            return 0.0

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

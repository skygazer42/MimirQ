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
from app.models.dataset import Dataset as DBDataset
from app.models.document import Document as DBDocument
from app.rag.core.logging import get_logger
from app.rag.embedding.utils import current_embedding_space_hash
from app.rag.retrieval.corpus_index import get_corpus_index
from app.rag.retrieval.hybrid import candidate_ranking, candidate_retrieval, channel_collection, corpus_channels
from app.rag.retrieval.hybrid.bm25_index import Bm25IndexMixin
from app.rag.retrieval.hybrid.channel_diagnostics import empty_channel_metrics
from app.rag.retrieval.hybrid.colbert_index import ColbertIndexMixin
from app.rag.retrieval.hybrid.common import (
    _RETRIEVAL_DISPLAY_CONTENT_KEY,
    _RETRIEVAL_EXPECTED_EMBEDDING_SPACE_KEY,
    NON_CRITICAL_RETRIEVER_FALLBACK_LOG,
    _float_or_default,
    _log_retriever_fallback,
)
from app.rag.retrieval.hybrid.dedup import DedupDiversityMixin
from app.rag.retrieval.hybrid.fusion import FusionMixin
from app.rag.retrieval.hybrid.lexical import LexicalDBMixin
from app.rag.retrieval.hybrid.post_process import PostProcessMixin
from app.rag.retrieval.hybrid.runtime_scope import ResolvedRetrievalScope, RetrievalScope, resolve_runtime_scope
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
    reject_current_inflight_retrieval_candidates,
    release_current_distributed_inflight_retrieval_candidates,
)
from app.services.corpus_cache_tokens import resolve_corpus_cache_token
from app.services.dataset_embedding_config import (
    DatasetEmbeddingRuntimeConfig,
    create_embeddings_for_runtime,
    resolve_dataset_embedding_runtime,
)
from app.services.rag_runtime_limiter import (
    run_blocking_retrieval_call,
    run_with_retrieval_backend_budget_sync,
)
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
    # Optional: when None, follow settings.SPARSE_RETRIEVAL_ENABLED dynamically (useful for tests / hot reload).
    # When set, acts as an explicit per-retriever override.
    sparse_enabled: bool | None = None
    sparse_provider: str = Field(default_factory=lambda: settings.SPARSE_RETRIEVAL_PROVIDER)
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
    enable_hierarchy_recall: bool = False
    hierarchy_family_collapse: bool = settings.HIERARCHY_RECALL_FAMILY_COLLAPSE
    hierarchy_overfetch_factor: int = max(1, int(settings.HIERARCHY_RECALL_OVERFETCH_FACTOR or 4))
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
        return bool(settings.SPARSE_RETRIEVAL_ENABLED)

    def _resolve_sparse_provider_status(self, *, sparse_enabled: bool) -> dict[str, Any]:
        from app.rag.retrieval.sparse import resolve_sparse_provider_capability

        return resolve_sparse_provider_capability(
            requested_provider=str(self.sparse_provider or ""),
            sparse_enabled=bool(sparse_enabled),
            splade_model_name=str(settings.SPARSE_SPLADE_MODEL_NAME or ""),
            default_provider="deterministic",
        )

    def _tenant_key(self, tenant_id: UUID | None) -> str:
        return str(tenant_id or settings.DEFAULT_TENANT_ID)

    @staticmethod
    def _resolve_tenant_uuid(tenant_id: UUID | None) -> UUID | None:
        if tenant_id is not None:
            return tenant_id
        try:
            return UUID(str(settings.DEFAULT_TENANT_ID or ""))
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
            max(1, int(settings.RAG_VECTOR_SHARD_MAX_CONCURRENCY or 1)),
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
            "candidates_count": len(entity_candidates or self.entity_candidates or []),
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
            "enabled": bool(settings.MILVUS_NATIVE_HYBRID),
            "used": False,
            "fallback_reason": None,
        }
        results: list[dict[str, Any]] = []
        can_try_native_hybrid = bool(
            native_hybrid_meta["enabled"]
            and str(settings.VECTOR_BACKEND or "").strip().lower() == "milvus"
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
                synonyms = parse_synonyms(str(settings.SPARSE_RETRIEVAL_SYNONYMS or ""))
                encoder = get_sparse_encoder(
                    provider=sparse_provider,
                    synonyms=synonyms,
                    synonyms_raw=str(settings.SPARSE_RETRIEVAL_SYNONYMS or ""),
                    model_name=str(settings.SPARSE_SPLADE_MODEL_NAME or ""),
                    device=str(settings.SPARSE_SPLADE_DEVICE or "cpu"),
                    batch_size=int(settings.SPARSE_SPLADE_BATCH_SIZE or 8),
                    max_length=int(settings.SPARSE_SPLADE_MAX_LENGTH or 256),
                    top_k=int(settings.SPARSE_SPLADE_TOP_K or 128),
                    min_weight=float(settings.SPARSE_SPLADE_MIN_WEIGHT or 0.0),
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
            meta["colpali_score"] = score
            item["metadata"] = meta
            item["colpali_score"] = score
            # Piggyback on lexical score so existing fusion logic can merge the channel.
            item["lexical_score"] = score
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
            self._last_sparse_provider_status = batch.collection.auxiliary.sparse.status
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
            sparse=corpus_channels.SparseSearchPolicy(
                enabled=self._effective_sparse_enabled(),
                provider=self.sparse_provider,
            ),
            native_hybrid_enabled=bool(settings.MILVUS_NATIVE_HYBRID),
            colbert_enabled=bool(settings.COLBERT_RETRIEVAL_ENABLED),
            colpali_enabled=bool(settings.COLPALI_RETRIEVAL_ENABLED),
            bm25_enabled=bool(settings.BM25_INDEX_ENABLED),
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
        )
        docs = self._results_to_documents(results, debug=debug, requested_k=requested_k)
        self._last_debug_metrics = debug
        return docs

    def _normalize_retrieval_query(self, query: str) -> tuple[str, str, Any]:
        max_query_chars = int(settings.RETRIEVAL_QUERY_MAX_CHARS or 8_000)
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
                profile=str(settings.RERANK_PROFILE or "").strip().lower() or None,
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
            "overfetch_enabled": search_k > requested_k,
            "overfetch_reasons": overfetch_reasons,
            "retrieval_profile": str(self.retrieval_profile or "").strip().lower() or None,
            "rerank_profile": str(settings.RERANK_PROFILE or "").strip().lower() or None,
            "hierarchy_family_collapse_enabled": bool(self._should_apply_hierarchy_family_collapse()),
            "hierarchy_overfetch_factor": max(1, int(self.hierarchy_overfetch_factor or 1)),
            "overfetch_multiplier": int(
                self.retrieval_overfetch_multiplier
                if self.retrieval_overfetch_multiplier is not None
                else settings.RETRIEVAL_OVERFETCH_MULTIPLIER or 1
            ),
            "overfetch_cap_k": int(
                self.retrieval_overfetch_max_k
                if self.retrieval_overfetch_max_k is not None
                else settings.RETRIEVAL_OVERFETCH_MAX_K or 0
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
            max_doc_ids = int(settings.MILVUS_EXPR_MAX_DOC_IDS or 0)
            debug["milvus_doc_id_pushdown_skipped"] = bool(
                settings.VECTOR_BACKEND == "milvus"
                and max_doc_ids > 0
                and self.document_ids
                and len(self.document_ids) > max_doc_ids
            )
            debug["milvus_expr_max_doc_ids"] = max_doc_ids
        except (TypeError, ValueError, AttributeError):
            debug["milvus_doc_id_pushdown_skipped"] = None

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
        debug["hybrid_results"] = len(batch.candidates)
        debug["channels"] = dict(batch.channel_metrics)
        channels_debug = debug["channels"]
        debug["retrieval_degraded"] = bool(channels_debug.get("retrieval_degraded", False))
        debug["retrieval_degraded_reasons"] = list(channels_debug.get("degraded_reasons") or [])
        debug["all_retrieval_channels_failed"] = bool(channels_debug.get("all_retrieval_channels_failed", False))
        debug["timing"] = self._safe_retrieval_timing_debug(channels_debug)
        debug["counts"] = self._safe_retrieval_count_debug(channels_debug)
        if batch.ranking is not None and batch.ranking.diversity:
            debug["diversity"] = dict(batch.ranking.diversity)

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
        debug["stitching_enabled"] = bool(settings.RAG_CONTEXT_STITCHING_ENABLED)
        return results

    def _results_to_documents(
        self,
        results: list[dict[str, Any]],
        *,
        debug: dict[str, Any],
        requested_k: int,
    ) -> list[Document]:
        prefix = list(results[:requested_k]) if results else []
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

    @staticmethod
    def _governance_policy_flags() -> tuple[bool, bool, bool]:
        return (
            bool(settings.RETRIEVAL_GOVERNANCE_PREFER_AUTHORITY),
            bool(settings.RETRIEVAL_GOVERNANCE_PREFER_LATEST),
            bool(settings.RETRIEVAL_GOVERNANCE_FILTER_SUPERSEDED),
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
        auth_boost_max = float(settings.RETRIEVAL_GOVERNANCE_AUTHORITY_BOOST_MAX or 0.0)
        latest_boost_max = float(settings.RETRIEVAL_GOVERNANCE_LATEST_BOOST_MAX or 0.0)
        window_days = max(1, int(settings.RETRIEVAL_GOVERNANCE_LATEST_WINDOW_DAYS or 180))
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

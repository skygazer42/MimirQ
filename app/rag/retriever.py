"""
Hybrid Retriever: Vector retrieval + BM25 + optional MMR diversity reranking.
Reference: RAG_Agent example repository. Retrieval modes and reranking strategies are configurable.
"""

import hashlib
import heapq
import math
import re
import threading
import time
from collections import Counter, OrderedDict
from dataclasses import dataclass, replace
from typing import Any, ClassVar, cast
from uuid import UUID

import jieba
from langchain_community.retrievers.bm25 import BM25Retriever
from langchain_core.callbacks import AsyncCallbackManagerForRetrieverRun, CallbackManagerForRetrieverRun
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from pydantic import ConfigDict, Field, PrivateAttr
from sqlalchemy import func, or_, text, tuple_
from sqlalchemy.orm import Session

from app.config.rerank_profile import resolve_rerank_search_k
from app.core.config import settings
from app.core.database import SessionLocal
from app.core.stream_events import emit_stream_event
from app.models.dataset import Dataset as DBDataset
from app.models.document import Document as DBDocument
from app.models.document import DocumentChunk
from app.rag.core.filters import match_metadata_filter
from app.rag.core.hashing import stable_hash
from app.rag.core.logging import get_logger
from app.rag.core.retrieval_profiles import is_recall_first_profile
from app.rag.embedding.utils import current_embedding_space_hash
from app.rag.preprocessing.stopwords import STOPWORDS
from app.rag.preprocessing.tokenization import tokenize_for_bm25
from app.rag.reranker.factory import get_reranker
from app.rag.reranker.types import RerankCandidate
from app.rag.retrieval.context_expansion import expand_ranked_chunk_results
from app.rag.retrieval.sibling_expand import select_document_expansion_mode
from app.rag.retrieval.sparse import SparseVector
from app.rag.retrieval_candidate_cache import (
    build_retrieval_candidate_cache_key,
    get_cached_retrieval_candidates,
    set_cached_retrieval_candidates,
)
from app.services.corpus_cache_tokens import resolve_corpus_cache_token
from app.services.dataset_embedding_config import (
    DatasetEmbeddingRuntimeConfig,
    create_embeddings_for_runtime,
    resolve_dataset_embedding_runtime,
)
from app.storage.vector.factory import get_vector_store
from app.storage.vector.milvus import get_milvus_adapter, resolve_collection_name

logger = get_logger("rag.retriever")


def _log_retriever_fallback(context: str, exc: BaseException) -> None:
    logger.debug("retriever fallback failed in %s: %s", context, exc, exc_info=True)


SPARSE_INDEX_DIR_FALLBACK = "./data/sparse_indexes"
COLBERT_INDEX_DIR_FALLBACK = "./data/colbert_indexes"
LEXICAL_DB_SEARCH_FAILED_LOG = "Lexical DB search failed: %s"
_RETRIEVAL_DISPLAY_CONTENT_KEY = "_retrieval_display_content"
_RETRIEVAL_QUESTIONS_CHANNEL_KEY = "_retrieval_questions_channel_applied"


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


class HybridRetriever(BaseRetriever):
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
    # Optional: when None, follow settings.SPARSE_RETRIEVAL_ENABLED dynamically (useful for tests / hot reload).
    # When set, acts as an explicit per-retriever override.
    sparse_enabled: bool | None = None
    sparse_provider: str = Field(default_factory=lambda: settings.SPARSE_RETRIEVAL_PROVIDER)
    dedup_enabled: bool = settings.RETRIEVAL_DEDUP_ENABLED
    dedup_jaccard_threshold: float = settings.RETRIEVAL_DEDUP_JACCARD_THRESHOLD
    dedup_max_compare: int = settings.RETRIEVAL_DEDUP_MAX_COMPARE
    max_chunks_per_doc: int = settings.RETRIEVAL_MAX_CHUNKS_PER_DOC
    max_chunks_per_page: int = getattr(settings, "RETRIEVAL_MAX_CHUNKS_PER_PAGE", 0)
    min_distinct_docs: int = settings.RETRIEVAL_MIN_DISTINCT_DOCS
    tenant_id: UUID | None = None
    # Optional: used for candidate-level ACL trimming when retrieval is not pre-scoped
    # by document_ids. When set, results are filtered fail-closed.
    account_id: str | None = None
    # Optional: dataset scope. When set, results are restricted to documents within the dataset.
    dataset_id: UUID | None = None
    document_ids: list[UUID] | None = None
    # Metadata filtering
    metadata_filter: dict[str, Any] | None = None
    entity_key: str | None = None
    partition_keys: list[str] | None = None
    entity_candidates: list[str] | None = None
    metadata_filter_enabled: bool = getattr(settings, "RETRIEVAL_METADATA_FILTER_ENABLED", True)
    retrieval_profile: str | None = None
    enable_hierarchy_recall: bool = False
    hierarchy_family_collapse: bool = False
    hierarchy_overfetch_factor: int = max(1, int(getattr(settings, "HIERARCHY_RECALL_OVERFETCH_FACTOR", 4) or 4))

    model_config = ConfigDict(arbitrary_types_allowed=True)

    _bm25_retrievers: dict[str, BM25Retriever] = PrivateAttr(default_factory=dict)
    _bm25_docs: dict[str, list[Document]] = PrivateAttr(default_factory=dict)
    _bm25_doc_ids: dict[str, set[str]] = PrivateAttr(default_factory=dict)
    _chunk_id_lookup: dict[str, dict[str, str]] = PrivateAttr(default_factory=dict)
    _bm25_build_locks: dict[str, threading.Lock] = PrivateAttr(default_factory=dict)
    # LRU order for per-tenant BM25 caches (prevents unbounded growth in multi-tenant deployments).
    _bm25_cache_order: "OrderedDict[str, None]" = PrivateAttr(default_factory=OrderedDict)
    _bm25_cache_lock: threading.Lock = PrivateAttr(default_factory=threading.Lock)
    # Cache versions per BM25 scope key (used to invalidate dataset-scoped indices after ingest).
    _bm25_cache_versions: dict[str, str] = PrivateAttr(default_factory=dict)
    # Best-effort debug metrics for the last retrieval call (per retriever instance).
    # Used by debug endpoints / observability to expose trimming/overfetch behavior.
    _last_debug_metrics: dict[str, Any] = PrivateAttr(default_factory=dict)
    # Per-query retrieval channel metrics (vector/BM25/lexical DB) for attribution/debugging.
    # Populated by `_hybrid_search` and embedded into `_last_debug_metrics` by `_get_relevant_documents`.
    _last_channel_metrics: dict[str, Any] = PrivateAttr(default_factory=dict)
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

    def _refresh_bm25_doc_ids(self, tenant_key: str, docs: list[Document] | None) -> None:
        if not docs:
            self._bm25_doc_ids.pop(tenant_key, None)
            return
        doc_ids: set[str] = set()
        for d in docs:
            meta = d.metadata or {}
            doc_id = meta.get("document_id")
            if doc_id is None:
                continue
            s = str(doc_id).strip()
            if s:
                doc_ids.add(s)
        self._bm25_doc_ids[tenant_key] = doc_ids

    def _tenant_key(self, tenant_id: UUID | None) -> str:
        return str(tenant_id or settings.DEFAULT_TENANT_ID)

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
        if not isinstance(value, list):
            return []
        out: list[str] = []
        seen: set[str] = set()
        for item in value:
            text = str(item or "").strip()
            if not text:
                continue
            key = text.casefold()
            if key in seen:
                continue
            seen.add(key)
            out.append(text[:200])
            if len(out) >= max(1, int(max_items or 1)):
                break
        return out

    def _augment_retrieval_corpus_text(self, *, content: str, metadata: dict[str, Any]) -> tuple[str, bool]:
        base = str(content or "")
        if bool(metadata.get("rich_metadata_header_applied")):
            return base, False

        questions = self._normalize_document_questions(metadata.get("document_questions"))
        if not questions:
            return base, False

        base_folded = base.casefold()
        additions = [question for question in questions if question.casefold() not in base_folded]
        if not additions:
            return base, False

        question_block = "Questions:\n" + "\n".join(f"- {question}" for question in additions)
        if not base.strip():
            return question_block, True
        return f"{base.rstrip()}\n\n{question_block}", True

    def _prepare_retrieval_document(self, doc: Document) -> Document:
        meta = dict(doc.metadata or {})
        display_content = str(meta.get(_RETRIEVAL_DISPLAY_CONTENT_KEY) or doc.page_content or "")
        retrieval_content, applied = self._augment_retrieval_corpus_text(content=display_content, metadata=meta)
        meta[_RETRIEVAL_DISPLAY_CONTENT_KEY] = display_content
        meta[_RETRIEVAL_QUESTIONS_CHANNEL_KEY] = bool(applied)
        try:
            return doc.model_copy(update={"page_content": retrieval_content, "metadata": meta})
        except Exception as exc:
            _log_retriever_fallback('_prepare_retrieval_document', exc)
            return Document(page_content=retrieval_content, metadata=meta, id=getattr(doc, "id", None))

    def _question_channel_overlap_score(
        self,
        *,
        query_tokens: list[str],
        metadata: dict[str, Any],
    ) -> float:
        questions = self._normalize_document_questions(metadata.get("document_questions"))
        if not questions or not query_tokens:
            return 0.0
        question_tokens = set(self._bm25_tokenize(" ".join(questions)))
        if not question_tokens:
            return 0.0
        overlap = set(query_tokens) & question_tokens
        if not overlap:
            return 0.0
        return min(1.0, float(len(overlap)) / float(max(1, len(set(query_tokens)))))

    def _bm25_scope_key(
        self,
        *,
        tenant_id: UUID,
        dataset_id: UUID | None,
        document_ids: list[UUID] | None,
    ) -> str:
        """
        Return the in-memory BM25 cache key for a retrieval scope.

        - document_ids scoped: cache per-tenant (small and request-specific)
        - dataset scoped: cache per (tenant, dataset) to keep indices smaller and easier to invalidate
        - open scope: cache per-tenant (legacy; usually disabled at the API layer)
        """
        tenant_key = self._tenant_key(tenant_id)
        if document_ids:
            return tenant_key
        if dataset_id is not None:
            return f"{tenant_key}:dataset:{dataset_id}"
        return tenant_key

    def _clear_bm25_cache_key(self, key: str) -> None:
        """Clear a single BM25 cache entry (in-memory only)."""
        self._bm25_retrievers.pop(key, None)
        self._bm25_docs.pop(key, None)
        self._bm25_doc_ids.pop(key, None)
        self._chunk_id_lookup.pop(key, None)
        self._bm25_build_locks.pop(key, None)
        self._bm25_cache_versions.pop(key, None)
        # Keep optional candidate indices aligned with the BM25 scope cache.
        self._sparse_doc_vectors.pop(key, None)
        self._sparse_build_locks.pop(key, None)
        self._colbert_index_cache.pop(key, None)
        self._colbert_build_locks.pop(key, None)
        with self._bm25_cache_lock:
            self._bm25_cache_order.pop(key, None)

    def _resolve_embedding_runtime(self, *, tenant_id: UUID | None) -> DatasetEmbeddingRuntimeConfig:
        if self.dataset_id is None or tenant_id is None:
            runtime = resolve_dataset_embedding_runtime(None)
            return replace(runtime, embedding_space_hash=current_embedding_space_hash())

        db = SessionLocal()
        try:
            row = (
                db.query(DBDataset.dataset_metadata)
                .filter(DBDataset.tenant_id == tenant_id, DBDataset.id == self.dataset_id)
                .first()
            )
            meta = row[0] if row else None
            runtime = resolve_dataset_embedding_runtime(dict(meta or {}) if isinstance(meta, dict) else {})
            if runtime.dataset_scoped:
                return runtime
            return replace(runtime, embedding_space_hash=current_embedding_space_hash())
        except Exception as exc:
            _log_retriever_fallback('_resolve_embedding_runtime', exc)
            runtime = resolve_dataset_embedding_runtime(None)
            return replace(runtime, embedding_space_hash=current_embedding_space_hash())
        finally:
            try:
                db.close()
            except Exception as exc:
                logger.debug("Ignoring non-critical retriever fallback failure: %s", exc)

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
        results = adapter.search(
            query_vector=query_vector,
            top_k=max(1, top_k * 2),
            metadata_filter=scoped_filter or None,
        )
        filtered = [r for r in results if float(r.get("score") or 0.0) >= float(score_threshold or 0.0)]
        return filtered[:top_k]

    def _bm25_dataset_cache_version(
        self,
        *,
        _tenant_id: UUID | None,
        _dataset_id: UUID,
    ) -> str:
        """
        Return a stable dataset version string for BM25 cache invalidation.

        Cross-process goal: ingestion workers can "touch" the dataset row, and API instances
        observe the updated `updated_at` to invalidate their in-memory BM25 indices.
        """
        tenant_uuid: UUID | None = _tenant_id
        if tenant_uuid is None:
            try:
                tenant_uuid = UUID(str(getattr(settings, "DEFAULT_TENANT_ID", "") or ""))
            except (TypeError, ValueError, AttributeError):
                tenant_uuid = None
        if tenant_uuid is None:
            return ""

        db = SessionLocal()
        try:
            from app.models.dataset import Dataset  # noqa: WPS433

            row = (
                db.query(Dataset.updated_at)
                .filter(Dataset.tenant_id == tenant_uuid, Dataset.id == _dataset_id)
                .first()
            )
            updated_at = row[0] if row else None
            try:
                return updated_at.isoformat() if updated_at is not None else ""
            except (TypeError, ValueError, AttributeError):
                return ""
        except Exception as exc:
            _log_retriever_fallback('_bm25_dataset_cache_version', exc)
            return ""
        finally:
            try:
                db.close()
            except Exception as exc:
                logger.debug("Ignoring non-critical retriever fallback failure: %s", exc)

    def _get_bm25_build_lock(self, tenant_key: str) -> threading.Lock:
        lock = self._bm25_build_locks.get(tenant_key)
        if lock is None:
            lock = threading.Lock()
            self._bm25_build_locks[tenant_key] = lock
        return lock

    def _get_sparse_build_lock(self, cache_key: str) -> threading.Lock:
        lock = self._sparse_build_locks.get(cache_key)
        if lock is None:
            lock = threading.Lock()
            self._sparse_build_locks[cache_key] = lock
        return lock

    def _get_colbert_build_lock(self, cache_key: str) -> threading.Lock:
        lock = self._colbert_build_locks.get(cache_key)
        if lock is None:
            lock = threading.Lock()
            self._colbert_build_locks[cache_key] = lock
        return lock

    def _resolve_candidate_cache_corpus_token(
        self,
        *,
        tenant_id: UUID | None,
        document_ids: list[UUID] | None,
    ) -> str | None:
        tenant_uuid = tenant_id or self.tenant_id
        if tenant_uuid is None:
            return None

        db = SessionLocal()
        try:
            return resolve_corpus_cache_token(
                db,
                tenant_id=tenant_uuid,
                dataset_id=self.dataset_id,
                document_ids=document_ids or [],
            )
        except Exception as exc:
            _log_retriever_fallback('_resolve_candidate_cache_corpus_token', exc)
            return None
        finally:
            try:
                db.close()
            except Exception as exc:
                logger.debug("Ignoring non-critical retriever fallback failure: %s", exc)

    def _build_sparse_index(
        self,
        *,
        cache_key: str,
        docs: list[Document],
        version_token: str | None = None,
    ) -> None:
        """
        Build (or rebuild) a sparse retrieval index for the current scope key.

        This is SPLADE-style sparse retrieval:
        - deterministic provider for tests/offline
        - optional SPLADE provider (HF/transformers) for production experiments (opt-in)

        Indices can be persisted to disk when enabled.
        """
        build_t0 = time.perf_counter()
        provider = str(self.sparse_provider or "deterministic").strip().lower()
        build_outcome = "ok"
        save_outcome: str | None = None
        from app.rag.retrieval.sparse_prometheus_metrics import (  # local import: optional dependency
            observe_sparse_index_build,
            observe_sparse_index_save,
        )

        try:
            from app.rag.retrieval.sparse import (
                SparseIndexStore,
                build_sparse_provider_config,
                get_sparse_encoder,
                parse_synonyms,
            )

            synonyms_raw = str(getattr(settings, "SPARSE_RETRIEVAL_SYNONYMS", "") or "")
            synonyms = parse_synonyms(synonyms_raw) if synonyms_raw.strip() else {}

            provider_config = build_sparse_provider_config(
                provider=provider,
                synonyms_raw=synonyms_raw,
                model_name=str(getattr(settings, "SPARSE_SPLADE_MODEL_NAME", "") or ""),
                device=str(getattr(settings, "SPARSE_SPLADE_DEVICE", "cpu") or "cpu"),
                batch_size=int(getattr(settings, "SPARSE_SPLADE_BATCH_SIZE", 8) or 8),
                max_length=int(getattr(settings, "SPARSE_SPLADE_MAX_LENGTH", 256) or 256),
                top_k=int(getattr(settings, "SPARSE_SPLADE_TOP_K", 128) or 128),
                min_weight=float(getattr(settings, "SPARSE_SPLADE_MIN_WEIGHT", 0.0) or 0.0),
            )

            encoder = get_sparse_encoder(
                provider=provider,
                synonyms=synonyms,
                synonyms_raw=synonyms_raw,
                model_name=str(getattr(settings, "SPARSE_SPLADE_MODEL_NAME", "") or ""),
                device=str(getattr(settings, "SPARSE_SPLADE_DEVICE", "cpu") or "cpu"),
                batch_size=int(getattr(settings, "SPARSE_SPLADE_BATCH_SIZE", 8) or 8),
                max_length=int(getattr(settings, "SPARSE_SPLADE_MAX_LENGTH", 256) or 256),
                top_k=int(getattr(settings, "SPARSE_SPLADE_TOP_K", 128) or 128),
                min_weight=float(getattr(settings, "SPARSE_SPLADE_MIN_WEIGHT", 0.0) or 0.0),
            )

            def _coerce(v: Any) -> SparseVector:
                if isinstance(v, SparseVector):
                    return v
                if isinstance(v, dict):
                    weights: dict[str, float] = {}
                    for k, w in v.items():
                        if k is None or w is None:
                            continue
                        try:
                            weights[str(k)] = float(w)
                        except (TypeError, ValueError, AttributeError):
                            continue
                    return SparseVector(weights=weights)
                return SparseVector(weights={})

            texts = [str(d.page_content or "") for d in (docs or []) if d is not None and d.id is not None]
            vecs = encoder.encode_batch(texts)

            out: dict[str, SparseVector] = {}
            idx = 0
            for d in docs or []:
                if d is None or d.id is None:
                    continue
                vec = vecs[idx] if idx < len(vecs) else SparseVector(weights={})
                out[str(d.id)] = _coerce(vec)
                idx += 1

            self._sparse_doc_vectors[cache_key] = out

            if bool(getattr(settings, "SPARSE_RETRIEVAL_INDEX_PERSIST_ENABLED", True)):
                try:
                    fp = self._sparse_corpus_fingerprint(docs)
                    store = SparseIndexStore(base_dir=str(getattr(settings, "SPARSE_RETRIEVAL_INDEX_DIR", SPARSE_INDEX_DIR_FALLBACK) or ""))
                    store.save(
                        cache_key=cache_key,
                        provider_config=provider_config,
                        corpus_fingerprint=fp,
                        vectors=out,
                        version_token=str(version_token or "").strip(),
                    )
                    save_outcome = "ok"
                except Exception as exc:
                    _log_retriever_fallback('_build_sparse_index', exc)
                    save_outcome = "error"
        except Exception as exc:
            _log_retriever_fallback('_build_sparse_index', exc)
            build_outcome = "error"
            raise
        finally:
            observe_sparse_index_build(
                provider=provider,
                kind="full",
                outcome=build_outcome,
                duration_sec=(time.perf_counter() - build_t0),
            )
            if save_outcome is not None:
                observe_sparse_index_save(provider=provider, outcome=save_outcome)

    def _upsert_sparse_index_incremental(
        self,
        *,
        cache_key: str,
        corpus_docs: list[Document],
        upsert_docs: list[Document],
        version_token: str | None = None,
    ) -> None:
        """
        Incrementally update the sparse index for a scope key.

        Rationale:
        - `_build_sparse_index` re-encodes the full corpus; that's fine for cold start but too expensive
          for frequent chunk-level upserts (document re-embed, patch, versioned re-index).
        - This helper updates/overwrites sparse vectors only for the provided `upsert_docs`, keeping the
          rest of the existing in-memory index intact.

        Safety:
        - If we don't have an existing index and the corpus is larger than the upsert batch, we fall
          back to a full rebuild to avoid a partial index that would cause false negatives.
        """
        if not upsert_docs:
            return

        build_t0 = time.perf_counter()
        build_outcome = "ok"
        load_outcome: str | None = None
        save_outcome: str | None = None

        provider = str(self.sparse_provider or "deterministic").strip().lower()

        from app.rag.retrieval.sparse_prometheus_metrics import (  # local import: optional dependency
            observe_sparse_index_build,
            observe_sparse_index_load,
            observe_sparse_index_save,
        )

        try:
            from app.rag.retrieval.sparse import (  # local import: keep optional deps isolated
                SparseIndexStore,
                build_sparse_provider_config,
                get_sparse_encoder,
                parse_synonyms,
            )

            synonyms_raw = str(getattr(settings, "SPARSE_RETRIEVAL_SYNONYMS", "") or "")
            synonyms = parse_synonyms(synonyms_raw) if synonyms_raw.strip() else {}

            provider_config = build_sparse_provider_config(
                provider=provider,
                synonyms_raw=synonyms_raw,
                model_name=str(getattr(settings, "SPARSE_SPLADE_MODEL_NAME", "") or ""),
                device=str(getattr(settings, "SPARSE_SPLADE_DEVICE", "cpu") or "cpu"),
                batch_size=int(getattr(settings, "SPARSE_SPLADE_BATCH_SIZE", 8) or 8),
                max_length=int(getattr(settings, "SPARSE_SPLADE_MAX_LENGTH", 256) or 256),
                top_k=int(getattr(settings, "SPARSE_SPLADE_TOP_K", 128) or 128),
                min_weight=float(getattr(settings, "SPARSE_SPLADE_MIN_WEIGHT", 0.0) or 0.0),
            )

            encoder = get_sparse_encoder(
                provider=provider,
                synonyms=synonyms,
                synonyms_raw=synonyms_raw,
                model_name=str(getattr(settings, "SPARSE_SPLADE_MODEL_NAME", "") or ""),
                device=str(getattr(settings, "SPARSE_SPLADE_DEVICE", "cpu") or "cpu"),
                batch_size=int(getattr(settings, "SPARSE_SPLADE_BATCH_SIZE", 8) or 8),
                max_length=int(getattr(settings, "SPARSE_SPLADE_MAX_LENGTH", 256) or 256),
                top_k=int(getattr(settings, "SPARSE_SPLADE_TOP_K", 128) or 128),
                min_weight=float(getattr(settings, "SPARSE_SPLADE_MIN_WEIGHT", 0.0) or 0.0),
            )

            sparse_vecs = self._sparse_doc_vectors.get(cache_key) or {}

            # Best-effort: load persisted index if we don't have an in-memory cache yet.
            if not sparse_vecs:
                if bool(getattr(settings, "SPARSE_RETRIEVAL_INDEX_PERSIST_ENABLED", True)):
                    load_outcome = "miss"
                    try:
                        fp = self._sparse_corpus_fingerprint(corpus_docs)
                        store = SparseIndexStore(
                            base_dir=str(getattr(settings, "SPARSE_RETRIEVAL_INDEX_DIR", SPARSE_INDEX_DIR_FALLBACK) or "")
                        )
                        loaded = store.load(
                            cache_key=cache_key,
                            provider_config=provider_config,
                            expected_fingerprint=fp,
                            expected_version_token=str(version_token or "").strip(),
                        )
                        if loaded:
                            sparse_vecs = loaded
                            load_outcome = "hit"
                    except Exception as exc:
                        _log_retriever_fallback('_upsert_sparse_index_incremental', exc)
                        sparse_vecs = {}
                        load_outcome = "error"
                else:
                    load_outcome = "skipped"

            # If the corpus is larger than the upsert batch and we don't have an existing index,
            # fall back to a full rebuild for correctness.
            if not sparse_vecs and corpus_docs and len(corpus_docs) > len(upsert_docs):
                build_outcome = "skipped"
                self._build_sparse_index(
                    cache_key=cache_key,
                    docs=corpus_docs,
                    version_token=str(version_token or "").strip(),
                )
                return

            def _coerce(v: Any) -> SparseVector:
                if isinstance(v, SparseVector):
                    return v
                if isinstance(v, dict):
                    weights: dict[str, float] = {}
                    for k, w in v.items():
                        if k is None or w is None:
                            continue
                        try:
                            weights[str(k)] = float(w)
                        except (TypeError, ValueError, AttributeError):
                            continue
                    return SparseVector(weights=weights)
                return SparseVector(weights={})

            texts: list[str] = []
            doc_ids: list[str] = []
            for d in upsert_docs:
                if d is None or d.id is None:
                    continue
                cid = str(d.id).strip()
                if not cid:
                    continue
                doc_ids.append(cid)
                texts.append(str(d.page_content or ""))

            if not doc_ids:
                build_outcome = "skipped"
                return

            vecs = encoder.encode_batch(texts)
            for cid, vec in zip(doc_ids, vecs, strict=False):
                sparse_vecs[cid] = _coerce(vec)

            self._sparse_doc_vectors[cache_key] = sparse_vecs

            if bool(getattr(settings, "SPARSE_RETRIEVAL_INDEX_PERSIST_ENABLED", True)):
                try:
                    fp = self._sparse_corpus_fingerprint(corpus_docs)
                    store = SparseIndexStore(
                        base_dir=str(getattr(settings, "SPARSE_RETRIEVAL_INDEX_DIR", SPARSE_INDEX_DIR_FALLBACK) or "")
                    )
                    store.save(
                        cache_key=cache_key,
                        provider_config=provider_config,
                        corpus_fingerprint=fp,
                        vectors=sparse_vecs,
                        version_token=str(version_token or "").strip(),
                    )
                    save_outcome = "ok"
                except Exception as exc:
                    _log_retriever_fallback('_upsert_sparse_index_incremental', exc)
                    save_outcome = "error"
        except Exception as exc:
            _log_retriever_fallback('_upsert_sparse_index_incremental', exc)
            build_outcome = "error"
            raise
        finally:
            observe_sparse_index_build(
                provider=provider,
                kind="incremental",
                outcome=build_outcome,
                duration_sec=(time.perf_counter() - build_t0),
            )
            if load_outcome is not None:
                observe_sparse_index_load(provider=provider, outcome=load_outcome)
            if save_outcome is not None:
                observe_sparse_index_save(provider=provider, outcome=save_outcome)

    def _colbert_corpus_fingerprint(self, docs: list[Document]) -> str:
        """
        Stable fingerprint for a ColBERT ANN index corpus.

        Uses chunk_id + pipeline markers so persisted indices can be invalidated after re-chunking.
        """
        parts: list[str] = []
        for d in docs or []:
            if d is None or d.id is None:
                continue
            cid = str(d.id)
            meta = d.metadata or {}
            pk = meta.get("doc_pipeline_key") or meta.get("pipeline_hash") or ""
            parts.append(f"{cid}:{pk}")
        parts.sort()
        h = hashlib.sha256()
        for p in parts:
            h.update(p.encode("utf-8", errors="ignore"))
            h.update(b"\n")
        return h.hexdigest()[:24]

    def _build_colbert_index(self, *, cache_key: str, docs: list[Document]) -> None:
        """
        Build (or rebuild) a ColBERT-style ANN index for the current scope key.

        Design:
        - Deterministic embedder for tests/offline (no model downloads)
        - Optional HF embedder (opt-in)
        - Persisted index to disk for fast cold-start in multi-process deployments
        """
        try:
            max_docs = int(getattr(settings, "COLBERT_RETRIEVAL_MAX_DOCS", 0) or 0)
        except (TypeError, ValueError, AttributeError):
            max_docs = 0
        if max_docs > 0 and len(docs or []) > max_docs:
            # Enforce a hard memory guard: don't build large matrices by accident.
            self._colbert_index_cache.pop(cache_key, None)
            return

        from app.rag.retrieval.colbert_ann import (
            ColbertAnnIndex,
            ColbertAnnIndexStore,
            build_colbert_provider_config,
            get_dense_embedder,
        )

        provider = str(getattr(settings, "COLBERT_RETRIEVAL_PROVIDER", "deterministic") or "deterministic").strip().lower()
        provider_config = build_colbert_provider_config(
            provider=provider,
            model_name=str(getattr(settings, "COLBERT_RETRIEVAL_MODEL_NAME", "") or ""),
            device=str(getattr(settings, "COLBERT_RETRIEVAL_DEVICE", "cpu") or "cpu"),
            batch_size=int(getattr(settings, "COLBERT_RETRIEVAL_BATCH_SIZE", 16) or 16),
            max_length=int(getattr(settings, "COLBERT_RETRIEVAL_MAX_LENGTH", 256) or 256),
            deterministic_dim=int(getattr(settings, "COLBERT_RETRIEVAL_EMBED_DIM", 64) or 64),
        )

        embedder = get_dense_embedder(
            provider=provider,
            model_name=str(getattr(settings, "COLBERT_RETRIEVAL_MODEL_NAME", "") or ""),
            device=str(getattr(settings, "COLBERT_RETRIEVAL_DEVICE", "cpu") or "cpu"),
            batch_size=int(getattr(settings, "COLBERT_RETRIEVAL_BATCH_SIZE", 16) or 16),
            max_length=int(getattr(settings, "COLBERT_RETRIEVAL_MAX_LENGTH", 256) or 256),
            deterministic_dim=int(getattr(settings, "COLBERT_RETRIEVAL_EMBED_DIM", 64) or 64),
        )

        # Build stable ordering for determinism (important for persisted format + tests).
        pairs: list[tuple[str, str]] = []
        for d in docs or []:
            if d is None or d.id is None:
                continue
            doc_id = str(d.id)
            text = str(d.page_content or "")
            pairs.append((doc_id, text))

        pairs.sort(key=lambda x: x[0])
        doc_ids = [p[0] for p in pairs]
        texts = [p[1] for p in pairs]

        if not texts:
            # Avoid numpy stack errors in deterministic embedder; empty corpora simply yield no hits.
            import numpy as np  # local import: used only for this guard path

            vecs = np.zeros((0, 1), dtype=np.float32)
        else:
            vecs = embedder.encode_batch(texts)

        fp = self._colbert_corpus_fingerprint(docs)
        index = ColbertAnnIndex(
            doc_ids=doc_ids,
            vectors=vecs,
            corpus_fingerprint=fp,
            provider_config=dict(provider_config),
        )
        self._colbert_index_cache[cache_key] = index

        if bool(getattr(settings, "COLBERT_RETRIEVAL_INDEX_PERSIST_ENABLED", True)):
            try:
                store = ColbertAnnIndexStore(base_dir=str(getattr(settings, "COLBERT_RETRIEVAL_INDEX_DIR", COLBERT_INDEX_DIR_FALLBACK) or ""))
                store.save(
                    cache_key=cache_key,
                    provider_config=provider_config,
                    corpus_fingerprint=fp,
                    doc_ids=doc_ids,
                    vectors=vecs,
                )
            except Exception as exc:
                logger.debug("Ignoring non-critical retriever fallback failure: %s", exc)

    def _upsert_colbert_index_incremental(
        self,
        *,
        cache_key: str,
        corpus_docs: list[Document],
        upsert_docs: list[Document],
    ) -> None:
        """
        Incrementally update a ColBERT ANN index for a scope key.

        This updates/overwrites vectors only for `upsert_docs` when an index already exists,
        avoiding a full re-embed of the corpus on each chunk-level upsert.
        """
        if not upsert_docs or not corpus_docs:
            return

        try:
            max_docs = int(getattr(settings, "COLBERT_RETRIEVAL_MAX_DOCS", 0) or 0)
        except (TypeError, ValueError, AttributeError):
            max_docs = 0
        if max_docs > 0 and len(corpus_docs or []) > max_docs:
            # Keep bounded resource usage by dropping the index for oversized scopes.
            self._colbert_index_cache.pop(cache_key, None)
            return

        from app.rag.retrieval.colbert_ann import (  # local import: optional deps
            ColbertAnnIndex,
            ColbertAnnIndexStore,
            build_colbert_provider_config,
            get_dense_embedder,
        )

        provider = str(getattr(settings, "COLBERT_RETRIEVAL_PROVIDER", "deterministic") or "deterministic").strip().lower()
        provider_config = build_colbert_provider_config(
            provider=provider,
            model_name=str(getattr(settings, "COLBERT_RETRIEVAL_MODEL_NAME", "") or ""),
            device=str(getattr(settings, "COLBERT_RETRIEVAL_DEVICE", "cpu") or "cpu"),
            batch_size=int(getattr(settings, "COLBERT_RETRIEVAL_BATCH_SIZE", 16) or 16),
            max_length=int(getattr(settings, "COLBERT_RETRIEVAL_MAX_LENGTH", 256) or 256),
            deterministic_dim=int(getattr(settings, "COLBERT_RETRIEVAL_EMBED_DIM", 64) or 64),
        )

        expected_fp = self._colbert_corpus_fingerprint(corpus_docs)

        base = self._colbert_index_cache.get(cache_key)
        base_cfg = dict(getattr(base, "provider_config", {}) or {}) if base is not None else {}
        base_ids = list(getattr(base, "doc_ids", []) or []) if base is not None else []
        base_vecs = getattr(base, "vectors", None) if base is not None else None
        if not base_ids or base_vecs is None or base_cfg != dict(provider_config):
            # No compatible index in memory: keep lazy-build semantics for cold start.
            return

        try:
            import numpy as np  # local import

            mat = np.asarray(base_vecs, dtype=np.float32)
            if mat.ndim != 2 or int(mat.shape[0]) != len(base_ids):
                return

            vec_by_id: dict[str, np.ndarray] = {
                str(doc_id): mat[i] for i, doc_id in enumerate(base_ids) if doc_id is not None
            }

            embedder = get_dense_embedder(
                provider=provider,
                model_name=str(getattr(settings, "COLBERT_RETRIEVAL_MODEL_NAME", "") or ""),
                device=str(getattr(settings, "COLBERT_RETRIEVAL_DEVICE", "cpu") or "cpu"),
                batch_size=int(getattr(settings, "COLBERT_RETRIEVAL_BATCH_SIZE", 16) or 16),
                max_length=int(getattr(settings, "COLBERT_RETRIEVAL_MAX_LENGTH", 256) or 256),
                deterministic_dim=int(getattr(settings, "COLBERT_RETRIEVAL_EMBED_DIM", 64) or 64),
            )

            up_ids: list[str] = []
            up_texts: list[str] = []
            for d in upsert_docs:
                if d is None or d.id is None:
                    continue
                cid = str(d.id).strip()
                if not cid:
                    continue
                up_ids.append(cid)
                up_texts.append(str(d.page_content or ""))
            if not up_ids:
                return

            # Correctness guard: if the base index is missing corpus docs *other than* the upsert batch,
            # do a full rebuild. Missing items that are part of this upsert are expected.
            corpus_ids = {str(d.id) for d in corpus_docs if d is not None and d.id is not None}
            missing = set(corpus_ids) - set(vec_by_id.keys())
            if missing and (missing - set(up_ids)):
                self._build_colbert_index(cache_key=cache_key, docs=corpus_docs)
                return

            up_mat = embedder.encode_batch(up_texts)
            up_mat = np.asarray(up_mat, dtype=np.float32)
            if up_mat.ndim != 2 or int(up_mat.shape[0]) != len(up_ids):
                return

            for cid, row in zip(up_ids, up_mat, strict=False):
                vec_by_id[str(cid)] = np.asarray(row, dtype=np.float32)

            # Re-pack to a stable, deterministic on-disk/in-memory layout.
            doc_ids = sorted(vec_by_id.keys())
            vectors = np.stack([vec_by_id[cid] for cid in doc_ids], axis=0).astype(np.float32, copy=False)
        except Exception as exc:
            _log_retriever_fallback('_upsert_colbert_index_incremental', exc)
            return

        index = ColbertAnnIndex(
            doc_ids=doc_ids,
            vectors=vectors,
            corpus_fingerprint=expected_fp,
            provider_config=dict(provider_config),
        )
        self._colbert_index_cache[cache_key] = index

        if bool(getattr(settings, "COLBERT_RETRIEVAL_INDEX_PERSIST_ENABLED", True)):
            try:
                store = ColbertAnnIndexStore(base_dir=str(getattr(settings, "COLBERT_RETRIEVAL_INDEX_DIR", COLBERT_INDEX_DIR_FALLBACK) or ""))
                store.save(
                    cache_key=cache_key,
                    provider_config=provider_config,
                    corpus_fingerprint=expected_fp,
                    doc_ids=doc_ids,
                    vectors=vectors,
                )
            except Exception as exc:
                logger.debug("Ignoring non-critical retriever fallback failure: %s", exc)

    def _sparse_corpus_fingerprint(self, docs: list[Document]) -> str:
        """
        Stable fingerprint for a sparse index corpus.

        Uses chunk_id + pipeline markers so persisted indices can be invalidated after re-chunking.
        """
        parts: list[str] = []
        for d in docs or []:
            if d is None or d.id is None:
                continue
            cid = str(d.id)
            meta = d.metadata or {}
            pk = meta.get("doc_pipeline_key") or meta.get("pipeline_hash") or ""
            parts.append(f"{cid}:{pk}")
        parts.sort()
        h = hashlib.sha256()
        for p in parts:
            h.update(p.encode("utf-8", errors="ignore"))
            h.update(b"\n")
        return h.hexdigest()[:24]

    def _bm25_cache_max_tenants(self) -> int:
        try:
            return max(0, int(getattr(settings, "BM25_CACHE_MAX_TENANTS", 0) or 0))
        except (TypeError, ValueError, AttributeError):
            return 0

    def _touch_bm25_cache(self, tenant_key: str) -> None:
        """
        Mark a tenant BM25 cache as recently used and evict LRU indices if needed.

        Eviction is best-effort: it only removes in-memory caches (BM25 retriever + docs),
        and will be rebuilt lazily on the next query for that tenant.
        """
        max_tenants = self._bm25_cache_max_tenants()
        if max_tenants <= 0:
            return

        evicted: list[str] = []
        with self._bm25_cache_lock:
            if tenant_key in self._bm25_cache_order:
                self._bm25_cache_order.move_to_end(tenant_key)
            else:
                self._bm25_cache_order[tenant_key] = None

            # Safety guard: avoid an infinite loop if something goes wrong.
            safety = len(self._bm25_cache_order) + 1
            while len(self._bm25_cache_order) > max_tenants and safety > 0:
                safety -= 1
                oldest = next(iter(self._bm25_cache_order))
                if oldest == tenant_key:
                    # Don't evict the tenant we're actively serving/building.
                    self._bm25_cache_order.move_to_end(oldest)
                    continue
                self._bm25_cache_order.pop(oldest, None)
                evicted.append(oldest)

        for key in evicted:
            self._bm25_retrievers.pop(key, None)
            self._bm25_docs.pop(key, None)
            self._bm25_doc_ids.pop(key, None)
            self._chunk_id_lookup.pop(key, None)
            self._bm25_build_locks.pop(key, None)
            self._bm25_cache_versions.pop(key, None)
            # Keep optional candidate indices aligned with the BM25 cache eviction.
            self._sparse_doc_vectors.pop(key, None)
            self._sparse_build_locks.pop(key, None)
            self._colbert_index_cache.pop(key, None)
            self._colbert_build_locks.pop(key, None)

        if evicted:
            logger.info("BM25 cache evicted %s keys (max=%s)", len(evicted), max_tenants)

    def _lazy_build_bm25_index(
        self,
        *,
        tenant_id: UUID | None,
        document_ids: list[UUID] | None,
        dataset_id: UUID | None = None,
    ) -> bool:
        """Build BM25 index on-demand to mitigate cold-start in multi-process deployments."""
        if not bool(getattr(settings, "BM25_INDEX_ENABLED", True)):
            return False
        if not bool(getattr(settings, "BM25_LAZY_BUILD_ENABLED", True)):
            return False

        tenant_uuid: UUID | None = tenant_id
        if tenant_uuid is None:
            try:
                tenant_uuid = UUID(str(getattr(settings, "DEFAULT_TENANT_ID", "") or ""))
            except (TypeError, ValueError, AttributeError):
                tenant_uuid = None
        if tenant_uuid is None:
            return False

        tenant_key = self._tenant_key(tenant_uuid)
        cache_key = self._bm25_scope_key(tenant_id=tenant_uuid, dataset_id=dataset_id, document_ids=document_ids)
        existing_retriever = self._bm25_retrievers.get(cache_key)
        existing_docs = self._bm25_docs.get(cache_key)
        if existing_retriever is not None and existing_docs is not None:
            # If a request scopes to specific documents, ensure those docs are covered by the current cache.
            # Lazy-built indices may have been created from a subset (e.g. first query after restart).
            if document_ids:
                indexed = self._bm25_doc_ids.get(cache_key)
                if indexed is None:
                    self._refresh_bm25_doc_ids(cache_key, existing_docs)
                    indexed = self._bm25_doc_ids.get(cache_key) or set()
                requested = {str(did) for did in document_ids if did is not None}
                missing = requested - set(indexed or set())
                if not missing:
                    self._touch_bm25_cache(cache_key)
                    return True
            else:
                self._touch_bm25_cache(cache_key)
                return True

        lock = self._get_bm25_build_lock(cache_key)
        with lock:
            existing_retriever = self._bm25_retrievers.get(cache_key)
            existing_docs = self._bm25_docs.get(cache_key)
            if existing_retriever is not None and existing_docs is not None:
                if document_ids:
                    indexed = self._bm25_doc_ids.get(cache_key)
                    if indexed is None:
                        self._refresh_bm25_doc_ids(cache_key, existing_docs)
                        indexed = self._bm25_doc_ids.get(cache_key) or set()
                    requested = {str(did) for did in document_ids if did is not None}
                    missing = requested - set(indexed or set())
                    if not missing:
                        self._touch_bm25_cache(cache_key)
                        return True
                else:
                    self._touch_bm25_cache(cache_key)
                    return True

            full_tenant = bool(getattr(settings, "BM25_LAZY_BUILD_FULL_TENANT", False))
            if not document_ids and not full_tenant and dataset_id is None:
                return False

            def _maybe_call(q, method_name: str, *args, **kwargs):
                fn = getattr(q, method_name, None)
                if not callable(fn):
                    return q
                try:
                    return fn(*args, **kwargs)
                except TypeError:
                    return q

            def _iter_rows(q, batch_size: int = 2000):
                fn = getattr(q, "yield_per", None)
                if callable(fn):
                    try:
                        return fn(batch_size)
                    except TypeError as exc:
                        logger.debug("Ignoring non-critical retriever fallback failure: %s", exc)
                all_fn = getattr(q, "all", None)
                if callable(all_fn):
                    return all_fn()
                return []

            def _unpack_chunk_row(row):
                try:
                    (
                        chunk_id,
                        content,
                        doc_metadata,
                        tenant_uuid_row,
                        document_uuid_row,
                        chunk_index,
                        page_number,
                    ) = row
                    return (
                        chunk_id,
                        content,
                        doc_metadata,
                        tenant_uuid_row,
                        document_uuid_row,
                        chunk_index,
                        page_number,
                    )
                except (TypeError, ValueError, AttributeError):
                    return (
                        getattr(row, "id", None),
                        getattr(row, "content", None),
                        getattr(row, "doc_metadata", None),
                        getattr(row, "tenant_id", None),
                        getattr(row, "document_id", None),
                        getattr(row, "chunk_index", None),
                        getattr(row, "page_number", None),
                    )

            max_chunks = max(0, int(getattr(settings, "BM25_LAZY_BUILD_MAX_CHUNKS", 0) or 0))
            db = SessionLocal()
            try:
                # If we already have an index and are missing requested docs, try to extend it.
                if existing_retriever is not None and existing_docs is not None and document_ids:
                    indexed = self._bm25_doc_ids.get(cache_key)
                    if indexed is None:
                        self._refresh_bm25_doc_ids(cache_key, existing_docs)
                        indexed = self._bm25_doc_ids.get(cache_key) or set()
                    requested = {str(did) for did in document_ids if did is not None}
                    missing = requested - set(indexed or set())

                    if missing:
                        existing_count = len(existing_docs)
                        if max_chunks and existing_count >= max_chunks:
                            # Memory cap reached: rebuild a scoped index for the requested documents.
                            q = (
                                db.query(
                                    DocumentChunk.id,
                                    DocumentChunk.content,
                                    DocumentChunk.doc_metadata,
                                    DocumentChunk.tenant_id,
                                    DocumentChunk.document_id,
                                    DocumentChunk.chunk_index,
                                    DocumentChunk.page_number,
                                )
                                .join(DBDocument)
                                .filter(DBDocument.status == "completed")
                                .filter(DBDocument.publication_status == "published")
                                .filter(DocumentChunk.tenant_id == tenant_uuid)
                                .filter(DocumentChunk.document_id.in_(document_ids))
                                .order_by(DocumentChunk.document_id.asc(), DocumentChunk.chunk_index.asc())
                            )
                            q = _maybe_call(q, "enable_eagerloads", False)
                            q = _maybe_call(q, "execution_options", stream_results=True)
                            if max_chunks:
                                q = q.limit(max_chunks)
                            docs: list[Document] = []
                            for row in _iter_rows(q, 2000):
                                (
                                    chunk_id,
                                    content,
                                    doc_metadata,
                                    tenant_uuid_row,
                                    document_uuid_row,
                                    chunk_index,
                                    page_number,
                                ) = _unpack_chunk_row(row)
                                meta = dict(doc_metadata or {})
                                meta.setdefault("tenant_id", str(tenant_uuid_row))
                                meta.setdefault("document_id", str(document_uuid_row))
                                meta.setdefault("chunk_index", int(chunk_index) if chunk_index is not None else None)
                                meta.setdefault("chunk_id", str(chunk_id))
                                meta.setdefault("source", meta.get("source", "unknown"))
                                if page_number is not None and not meta.get("page"):
                                    meta["page"] = page_number
                                meta.setdefault("image_id", meta.get("image_id"))
                                meta.setdefault("image_url", meta.get("image_url"))
                                docs.append(Document(page_content=content or "", id=str(chunk_id), metadata=meta))
                            if not docs:
                                return True
                            self._build_bm25_index_from_documents(docs, tenant_id=tenant_uuid, cache_key=cache_key)
                            logger.info(
                                "BM25 lazy-built (scoped rebuild) %s chunks for tenant %s missing_docs=%s cap=%s",
                                len(docs),
                                cache_key,
                                len(missing),
                                max_chunks,
                            )
                            return True

                        q = (
                            db.query(
                                DocumentChunk.id,
                                DocumentChunk.content,
                                DocumentChunk.doc_metadata,
                                DocumentChunk.tenant_id,
                                DocumentChunk.document_id,
                                DocumentChunk.chunk_index,
                                DocumentChunk.page_number,
                            )
                            .join(DBDocument)
                            .filter(DBDocument.status == "completed")
                            .filter(DBDocument.publication_status == "published")
                            .filter(DocumentChunk.tenant_id == tenant_uuid)
                            .filter(DocumentChunk.document_id.in_(list(missing)))
                            .order_by(DocumentChunk.document_id.asc(), DocumentChunk.chunk_index.asc())
                        )
                        q = _maybe_call(q, "enable_eagerloads", False)
                        q = _maybe_call(q, "execution_options", stream_results=True)
                        if max_chunks:
                            remaining = max(0, int(max_chunks) - int(existing_count))
                            if remaining <= 0:
                                return True
                            q = q.limit(remaining)
                        bm25_docs: list[Document] = []
                        for row in _iter_rows(q, 2000):
                            (
                                chunk_id,
                                content,
                                doc_metadata,
                                tenant_uuid_row,
                                document_uuid_row,
                                chunk_index,
                                page_number,
                            ) = _unpack_chunk_row(row)
                            meta = dict(doc_metadata or {})
                            meta.setdefault("tenant_id", str(tenant_uuid_row))
                            meta.setdefault("document_id", str(document_uuid_row))
                            meta.setdefault("chunk_index", int(chunk_index) if chunk_index is not None else None)
                            meta.setdefault("chunk_id", str(chunk_id))
                            meta.setdefault("source", meta.get("source", "unknown"))
                            if page_number is not None and not meta.get("page"):
                                meta["page"] = page_number
                            meta.setdefault("image_id", meta.get("image_id"))
                            meta.setdefault("image_url", meta.get("image_url"))
                            bm25_docs.append(Document(page_content=content or "", id=str(chunk_id), metadata=meta))
                        if not bm25_docs:
                            return True
                        self.upsert_bm25_documents(bm25_docs, tenant_id=tenant_uuid)
                        logger.info(
                            "BM25 lazy-extended %s chunks for tenant %s (missing_docs=%s)",
                            len(bm25_docs),
                            tenant_key,
                            len(missing),
                        )
                        return True

                # Cold start: build an initial index (full tenant or scoped document_ids).
                q = (
                    db.query(
                        DocumentChunk.id,
                        DocumentChunk.content,
                        DocumentChunk.doc_metadata,
                        DocumentChunk.tenant_id,
                        DocumentChunk.document_id,
                        DocumentChunk.chunk_index,
                        DocumentChunk.page_number,
                    )
                    .join(DBDocument)
                    .filter(DBDocument.status == "completed")
                    .filter(DBDocument.publication_status == "published")
                    .filter(DocumentChunk.tenant_id == tenant_uuid)
                )
                q = _maybe_call(q, "enable_eagerloads", False)
                q = _maybe_call(q, "execution_options", stream_results=True)
                if document_ids:
                    q = q.filter(DocumentChunk.document_id.in_(document_ids))
                elif dataset_id is not None:
                    q = q.filter(DBDocument.dataset_id == dataset_id)
                q = q.order_by(DocumentChunk.document_id.asc(), DocumentChunk.chunk_index.asc())
                if max_chunks:
                    q = q.limit(max_chunks)
                docs: list[Document] = []
                for row in _iter_rows(q, 2000):
                    (
                        chunk_id,
                        content,
                        doc_metadata,
                        tenant_uuid_row,
                        document_uuid_row,
                        chunk_index,
                        page_number,
                    ) = _unpack_chunk_row(row)
                    meta = dict(doc_metadata or {})
                    meta.setdefault("tenant_id", str(tenant_uuid_row))
                    meta.setdefault("document_id", str(document_uuid_row))
                    meta.setdefault("chunk_index", int(chunk_index) if chunk_index is not None else None)
                    meta.setdefault("chunk_id", str(chunk_id))
                    meta.setdefault("source", meta.get("source", "unknown"))
                    if page_number is not None and not meta.get("page"):
                        meta["page"] = page_number
                    meta.setdefault("image_id", meta.get("image_id"))
                    meta.setdefault("image_url", meta.get("image_url"))
                    docs.append(Document(page_content=content or "", id=str(chunk_id), metadata=meta))
                if not docs:
                    return False
                self._build_bm25_index_from_documents(docs, tenant_id=tenant_uuid, cache_key=cache_key)
                logger.info(
                    "BM25 lazy-built %s chunks for scope %s (doc_ids=%s)",
                    len(docs),
                    cache_key,
                    len(document_ids) if document_ids else 0,
                )
                return True
            except Exception as exc:
                logger.warning("BM25 lazy build failed for scope %s: %s", cache_key, str(exc)[:200])
                return False
            finally:
                try:
                    db.close()
                except Exception as exc:
                    logger.debug("Ignoring non-critical retriever fallback failure: %s", exc)

    @staticmethod
    def _bm25_tokenize(text: str) -> list[str]:
        """Tokenize text for BM25 (shared)."""
        return tokenize_for_bm25(text)

    def build_bm25_index(self, chunks: list[DocumentChunk], tenant_id: UUID | None = None):
        """Build/rebuild BM25 index."""
        if not chunks:
            return

        docs: list[Document] = []
        for chunk in chunks:
            meta = dict(chunk.doc_metadata or {})
            meta.setdefault("tenant_id", str(chunk.tenant_id))
            meta.setdefault("document_id", str(chunk.document_id))
            meta.setdefault("chunk_index", chunk.chunk_index)
            meta.setdefault("chunk_id", str(chunk.id))
            meta.setdefault("source", meta.get("source", "unknown"))
            meta.setdefault("page", chunk.page_number or meta.get("page"))
            meta.setdefault("image_id", meta.get("image_id"))
            meta.setdefault("image_url", meta.get("image_url"))

            docs.append(Document(page_content=chunk.content, id=str(chunk.id), metadata=meta))
        self._build_bm25_index_from_documents(docs, tenant_id=tenant_id)

    def _build_bm25_index_from_documents(
        self,
        docs: list[Document],
        *,
        tenant_id: UUID | None = None,
        cache_key: str | None = None,
    ) -> None:
        """Build BM25 from LangChain Document list (avoids dependency on ORM objects)."""
        if not docs:
            return
        docs = [self._prepare_retrieval_document(doc) for doc in docs if doc is not None]
        if not docs:
            return
        key = str(cache_key) if cache_key is not None else self._tenant_key(tenant_id)
        retriever = BM25Retriever.from_documents(docs, preprocess_func=self._bm25_tokenize, k=10)
        self._bm25_retrievers[key] = retriever
        self._bm25_docs[key] = docs
        self._refresh_bm25_doc_ids(key, docs)
        lookup: dict[str, str] = {}
        for d in docs:
            meta = d.metadata or {}
            doc_id = meta.get("document_id")
            doc_pipeline_key = meta.get("doc_pipeline_key")
            chunk_index = meta.get("chunk_index")
            if doc_id is None or chunk_index is None or d.id is None:
                continue
            if doc_pipeline_key is not None:
                lookup[f"{doc_pipeline_key}:{chunk_index}"] = str(d.id)
            lookup[f"{doc_id}:{chunk_index}"] = str(d.id)
        self._chunk_id_lookup[key] = lookup
        self._touch_bm25_cache(key)
        logger.info("BM25 index built with %s chunks for scope %s", len(docs), key)

    def build_bm25_index_from_db(
        self,
        db: Session,
        *,
        tenant_id: UUID,
        dataset_id: UUID | None = None,
        document_ids: list[UUID] | None = None,
        max_chunks: int = 0,
        batch_size: int = 2000,
    ) -> int:
        docs = self._load_retrieval_docs_from_db(
            db,
            tenant_id=tenant_id,
            dataset_id=dataset_id,
            document_ids=document_ids,
            max_chunks=max_chunks,
            batch_size=batch_size,
        )
        cache_key = self._bm25_scope_key(
            tenant_id=tenant_id,
            dataset_id=dataset_id if not document_ids else None,
            document_ids=document_ids,
        )
        self._build_bm25_index_from_documents(docs, tenant_id=tenant_id, cache_key=cache_key)
        return len(docs)

    def _load_retrieval_docs_from_db(
        self,
        db: Session,
        *,
        tenant_id: UUID,
        dataset_id: UUID | None = None,
        document_ids: list[UUID] | None = None,
        max_chunks: int = 0,
        batch_size: int = 2000,
    ) -> list[Document]:
        """
        Load retrieval documents from DB with streaming to avoid large ORM materialization spikes.

        This corpus is reused by BM25, sparse, and ColBERT rebuild paths.
        """
        q = (
            db.query(
                DocumentChunk.id,
                DocumentChunk.content,
                DocumentChunk.doc_metadata,
                DocumentChunk.tenant_id,
                DocumentChunk.document_id,
                DocumentChunk.chunk_index,
                DocumentChunk.page_number,
            )
            .join(DBDocument)
            .filter(DBDocument.status == "completed")
            .filter(DBDocument.publication_status == "published")
            .filter(DocumentChunk.tenant_id == tenant_id)
            .order_by(DocumentChunk.document_id.asc(), DocumentChunk.chunk_index.asc())
            .enable_eagerloads(False)
            .execution_options(stream_results=True)
        )
        if dataset_id is not None:
            q = q.filter(DBDocument.dataset_id == dataset_id)
        if document_ids:
            q = q.filter(DocumentChunk.document_id.in_(document_ids))
        if max_chunks and int(max_chunks) > 0:
            q = q.limit(int(max_chunks))

        docs: list[Document] = []
        for (
            chunk_id,
            content,
            doc_metadata,
            tenant_uuid,
            document_uuid,
            chunk_index,
            page_number,
        ) in q.yield_per(int(batch_size)):
            meta = dict(doc_metadata or {})
            meta.setdefault("tenant_id", str(tenant_uuid))
            meta.setdefault("document_id", str(document_uuid))
            meta.setdefault("chunk_index", int(chunk_index) if chunk_index is not None else None)
            meta.setdefault("chunk_id", str(chunk_id))
            meta.setdefault("source", meta.get("source", "unknown"))
            if page_number is not None and not meta.get("page"):
                meta["page"] = page_number
            meta.setdefault("image_id", meta.get("image_id"))
            meta.setdefault("image_url", meta.get("image_url"))
            docs.append(self._prepare_retrieval_document(Document(page_content=content or "", id=str(chunk_id), metadata=meta)))
        return docs

    def rebuild_persisted_retrieval_indexes(
        self,
        db: Session,
        *,
        tenant_id: UUID,
        dataset_id: UUID | None = None,
        batch_size: int = 2000,
    ) -> dict[str, Any]:
        """
        Rebuild persisted retrieval artifacts for a tenant/dataset scope.

        This is the single-node operational entry point for sparse / ColBERT index rebuilds.
        It refreshes the shared retrieval corpus from Postgres and writes persisted index artifacts
        for the active retrieval channels.
        """
        docs = self._load_retrieval_docs_from_db(
            db,
            tenant_id=tenant_id,
            dataset_id=dataset_id,
            document_ids=None,
            max_chunks=0,
            batch_size=batch_size,
        )
        cache_key = self._bm25_scope_key(
            tenant_id=tenant_id,
            dataset_id=dataset_id,
            document_ids=None,
        )
        self._build_bm25_index_from_documents(docs, tenant_id=tenant_id, cache_key=cache_key)

        sparse_rebuilt = False
        if bool(getattr(settings, "SPARSE_RETRIEVAL_ENABLED", False)) and docs:
            sparse_version_token = self._resolve_candidate_cache_corpus_token(
                tenant_id=tenant_id,
                document_ids=None,
            )
            self._build_sparse_index(
                cache_key=cache_key,
                docs=docs,
                version_token=sparse_version_token,
            )
            sparse_rebuilt = bool(self._sparse_doc_vectors.get(cache_key))

        colbert_rebuilt = False
        if bool(getattr(settings, "COLBERT_RETRIEVAL_ENABLED", False)) and docs:
            self._build_colbert_index(cache_key=cache_key, docs=docs)
            colbert_rebuilt = bool(self._colbert_index_cache.get(cache_key) is not None)

        return {
            "tenant_id": str(tenant_id),
            "dataset_id": str(dataset_id) if dataset_id is not None else None,
            "cache_key": cache_key,
            "doc_count": len(docs),
            "bm25_rebuilt": bool(docs),
            "sparse_rebuilt": sparse_rebuilt,
            "colbert_rebuilt": colbert_rebuilt,
        }

    def upsert_bm25_documents(self, docs: list[Document], tenant_id: UUID | None = None):
        """
        Incrementally update BM25 index (avoids full DB scan each time).
        Note: BM25Retriever itself doesn't support incremental training, so we merge in-memory and rebuild.
        This still significantly reduces DB query overhead, suitable for large-scale knowledge bases.
        """
        if not docs:
            return
        tenant_uuid: UUID | None = tenant_id
        if tenant_uuid is None:
            try:
                tenant_uuid = UUID(str(getattr(settings, "DEFAULT_TENANT_ID", "") or ""))
            except (TypeError, ValueError, AttributeError):
                tenant_uuid = None
        if tenant_uuid is None:
            return
        docs = [self._prepare_retrieval_document(doc) for doc in docs if doc is not None]
        if not docs:
            return

        cache_key = self._bm25_scope_key(
            tenant_id=tenant_uuid,
            dataset_id=self.dataset_id,
            document_ids=None,
        )
        existing = self._bm25_docs.get(cache_key) or []
        merged: dict[str, Document] = {str(d.id): d for d in existing if d.id is not None}
        for d in docs:
            if d.id is None:
                continue
            merged[str(d.id)] = d

        merged_docs = list(merged.values())
        retriever = BM25Retriever.from_documents(
            merged_docs,
            preprocess_func=self._bm25_tokenize,
            k=10,
        )
        self._bm25_retrievers[cache_key] = retriever
        self._bm25_docs[cache_key] = merged_docs
        self._refresh_bm25_doc_ids(cache_key, merged_docs)
        lookup: dict[str, str] = {}
        for d in merged_docs:
            meta = d.metadata or {}
            doc_id = meta.get("document_id")
            doc_pipeline_key = meta.get("doc_pipeline_key")
            chunk_index = meta.get("chunk_index")
            if doc_id is None or chunk_index is None or d.id is None:
                continue
            if doc_pipeline_key is not None:
                lookup[f"{doc_pipeline_key}:{chunk_index}"] = str(d.id)
            lookup[f"{doc_id}:{chunk_index}"] = str(d.id)
        self._chunk_id_lookup[cache_key] = lookup
        self._touch_bm25_cache(cache_key)
        logger.info("BM25 index updated to %s chunks for scope %s", len(merged_docs), cache_key)

        # Optional: keep sparse retrieval index in sync with the BM25 scope docs.
        if self._effective_sparse_enabled():
            try:
                with self._get_sparse_build_lock(cache_key):
                    sparse_version_token = self._resolve_candidate_cache_corpus_token(
                        tenant_id=tenant_uuid,
                        document_ids=None,
                    )
                    self._upsert_sparse_index_incremental(
                        cache_key=cache_key,
                        corpus_docs=merged_docs,
                        upsert_docs=docs,
                        version_token=sparse_version_token,
                    )
            except Exception as exc:
                logger.warning("Sparse index update failed for scope %s: %s", cache_key, str(exc)[:200])

        # Optional: keep ColBERT ANN index in sync for hot scopes (incremental upserts).
        if bool(getattr(settings, "COLBERT_RETRIEVAL_ENABLED", False)):
            try:
                with self._get_colbert_build_lock(cache_key):
                    self._upsert_colbert_index_incremental(
                        cache_key=cache_key,
                        corpus_docs=merged_docs,
                        upsert_docs=docs,
                    )
            except Exception as exc:
                logger.warning("ColBERT index update failed for scope %s: %s", cache_key, str(exc)[:200])

    def remove_document_from_bm25_index(self, document_id: UUID, tenant_id: UUID | None = None):
        """Remove all chunks of a specified document from the BM25 index."""
        self.remove_from_bm25_index_by_metadata_filter(
            tenant_id=tenant_id,
            metadata_filter={"document_id": {"$eq": str(document_id)}},
        )

    def remove_from_bm25_index_by_metadata_filter(
        self,
        *,
        tenant_id: UUID | None = None,
        metadata_filter: dict[str, Any] | None = None,
    ) -> int:
        """
        Remove BM25 docs that match a metadata_filter (in-memory only).

        This is used for versioned re-indexing (e.g. delete only a specific doc_pipeline_key),
        without dropping other versions that may still serve as the active pipeline.
        """
        if not metadata_filter or not isinstance(metadata_filter, dict):
            return 0

        tenant_key = self._tenant_key(tenant_id)
        scope_prefix = f"{tenant_key}:dataset:"
        scope_keys = [
            k
            for k in set(list(self._bm25_docs.keys()) + list(self._bm25_retrievers.keys()))
            if k == tenant_key or str(k).startswith(scope_prefix)
        ] or [tenant_key]

        total_removed = 0
        for scope_key in scope_keys:
            existing = self._bm25_docs.get(scope_key) or []
            if not existing:
                continue

            before_ids = {str(d.id) for d in existing if d is not None and d.id is not None}
            filtered = [d for d in existing if not self._match_metadata_filter((d.metadata or {}), metadata_filter)]
            after_ids = {str(d.id) for d in filtered if d is not None and d.id is not None}

            removed = int(len(existing) - len(filtered))
            if removed <= 0:
                continue

            removed_ids = before_ids - after_ids

            retriever = (
                BM25Retriever.from_documents(
                    filtered,
                    preprocess_func=self._bm25_tokenize,
                    k=10,
                )
                if filtered
                else None
            )

            if retriever is None:
                self._bm25_retrievers.pop(scope_key, None)
                self._bm25_docs.pop(scope_key, None)
                self._bm25_doc_ids.pop(scope_key, None)
                self._chunk_id_lookup.pop(scope_key, None)
                self._bm25_build_locks.pop(scope_key, None)
                self._bm25_cache_versions.pop(scope_key, None)
                with self._bm25_cache_lock:
                    self._bm25_cache_order.pop(scope_key, None)
                # Keep optional candidate indices in sync (avoid stale/false negatives).
                self._sparse_doc_vectors.pop(scope_key, None)
                self._colbert_index_cache.pop(scope_key, None)
                logger.info(
                    "BM25 index cleared for scope %s after filtered deletion (removed=%s)",
                    scope_key,
                    removed,
                )
                total_removed += removed
                continue

            self._bm25_retrievers[scope_key] = retriever
            self._bm25_docs[scope_key] = filtered
            self._refresh_bm25_doc_ids(scope_key, filtered)
            lookup: dict[str, str] = {}
            for d in filtered:
                meta = d.metadata or {}
                doc_id = meta.get("document_id")
                doc_pipeline_key = meta.get("doc_pipeline_key")
                chunk_index = meta.get("chunk_index")
                if doc_id is None or chunk_index is None or d.id is None:
                    continue
                if doc_pipeline_key is not None:
                    lookup[f"{doc_pipeline_key}:{chunk_index}"] = str(d.id)
                lookup[f"{doc_id}:{chunk_index}"] = str(d.id)
            self._chunk_id_lookup[scope_key] = lookup
            self._touch_bm25_cache(scope_key)

            if removed_ids:
                # Best-effort: update sparse index by removing vectors for deleted chunks.
                if self._effective_sparse_enabled():
                    try:
                        with self._get_sparse_build_lock(scope_key):
                            vecs = self._sparse_doc_vectors.get(scope_key) or {}
                            if vecs:
                                for cid in removed_ids:
                                    vecs.pop(cid, None)
                                self._sparse_doc_vectors[scope_key] = vecs
                    except Exception as exc:
                        logger.debug("Ignoring non-critical retriever fallback failure: %s", exc)

                # Best-effort: update ColBERT ANN index by removing deleted chunk vectors.
                if bool(getattr(settings, "COLBERT_RETRIEVAL_ENABLED", False)):
                    try:
                        with self._get_colbert_build_lock(scope_key):
                            idx = self._colbert_index_cache.get(scope_key)
                            if idx is not None:
                                ids0 = list(getattr(idx, "doc_ids", []) or [])
                                vecs0 = getattr(idx, "vectors", None)
                                if ids0 and vecs0 is not None:
                                    try:
                                        import numpy as np

                                        mat = np.asarray(vecs0, dtype=np.float32)
                                        keep: list[int] = [i for i, cid in enumerate(ids0) if str(cid) not in removed_ids]
                                        if not keep:
                                            self._colbert_index_cache.pop(scope_key, None)
                                        else:
                                            new_ids = [str(ids0[i]) for i in keep]
                                            new_mat = mat[keep, :]
                                            fp = self._colbert_corpus_fingerprint(filtered)
                                            from app.rag.retrieval.colbert_ann import ColbertAnnIndex  # noqa: WPS433

                                            self._colbert_index_cache[scope_key] = ColbertAnnIndex(
                                                doc_ids=new_ids,
                                                vectors=new_mat,
                                                corpus_fingerprint=fp,
                                                provider_config=dict(getattr(idx, "provider_config", {}) or {}),
                                            )
                                    except Exception as exc:
                                        logger.debug("Ignoring non-critical retriever fallback failure: %s", exc)
                    except Exception as exc:
                        logger.debug("Ignoring non-critical retriever fallback failure: %s", exc)

            logger.info("BM25 index removed %s docs by metadata_filter for scope %s", removed, scope_key)
            total_removed += removed

        return total_removed

    def clear_bm25_cache(self) -> None:
        """Clear all cached BM25 indices (in-memory only)."""
        self._bm25_retrievers.clear()
        self._bm25_docs.clear()
        self._bm25_doc_ids.clear()
        self._chunk_id_lookup.clear()
        self._bm25_build_locks.clear()
        self._bm25_cache_versions.clear()
        self._sparse_doc_vectors.clear()
        self._sparse_build_locks.clear()
        self._colbert_index_cache.clear()
        self._colbert_build_locks.clear()
        with self._bm25_cache_lock:
            self._bm25_cache_order.clear()

    def _search_bm25(
        self,
        query: str,
        top_k: int = 10,
        document_ids: list[UUID] | None = None,
        tenant_id: UUID | None = None,
        metadata_filter: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """BM25 keyword retrieval (internal use, returns dicts with scores)."""
        if not bool(getattr(settings, "BM25_INDEX_ENABLED", True)):
            return []

        tenant_uuid: UUID | None = tenant_id
        if tenant_uuid is None:
            try:
                tenant_uuid = UUID(str(getattr(settings, "DEFAULT_TENANT_ID", "") or ""))
            except (TypeError, ValueError, AttributeError):
                tenant_uuid = None
        if tenant_uuid is None:
            return []

        dataset_scope_id: UUID | None = None
        if self.dataset_id is not None and not (document_ids or []):
            dataset_scope_id = self.dataset_id

        cache_key = self._bm25_scope_key(tenant_id=tenant_uuid, dataset_id=dataset_scope_id, document_ids=document_ids)

        current_version: str | None = None
        if dataset_scope_id is not None:
            current_version = self._bm25_dataset_cache_version(
                _tenant_id=tenant_uuid,
                _dataset_id=dataset_scope_id,
            )
            if current_version:
                cached_version = self._bm25_cache_versions.get(cache_key)
                if cached_version != current_version:
                    # Dataset was updated since this index was built. Fail closed by rebuilding.
                    self._clear_bm25_cache_key(cache_key)
            else:
                # If we can't determine a stable version (e.g., offline test mode / DB down),
                # do not invalidate existing in-memory indices.
                current_version = None

        retriever = self._bm25_retrievers.get(cache_key)
        docs = self._bm25_docs.get(cache_key)
        if retriever is None or docs is None:
            self._lazy_build_bm25_index(
                tenant_id=tenant_uuid,
                document_ids=document_ids,
                dataset_id=dataset_scope_id,
            )
            retriever = self._bm25_retrievers.get(cache_key)
            docs = self._bm25_docs.get(cache_key)
            if retriever is None or docs is None:
                logger.warning("BM25 index not initialized, skipping keyword search")
                return []

        if dataset_scope_id is not None and current_version:
            self._bm25_cache_versions[cache_key] = current_version

        self._touch_bm25_cache(cache_key)

        allowed_ids = {str(doc_id) for doc_id in document_ids} if document_ids else None
        processed_query = retriever.preprocess_func(query)
        scores = retriever.vectorizer.get_scores(processed_query)  # type: ignore[attr-defined]
        query_tokens = [str(token or "").strip() for token in processed_query if str(token or "").strip()]

        results: list[dict[str, Any]] = []
        for doc, score in zip(docs, scores, strict=False):
            meta = doc.metadata or {}
            if allowed_ids and str(meta.get("document_id")) not in allowed_ids:
                continue
            # Apply metadata filter if provided
            if metadata_filter and self.metadata_filter_enabled:
                if not self._match_metadata_filter(meta, metadata_filter):
                    continue
            question_channel_score = self._question_channel_overlap_score(query_tokens=query_tokens, metadata=meta)
            final_score = float(score) + float(question_channel_score or 0.0)
            results.append(
                {
                    "chunk_id": doc.id,
                    "content": self._result_content_from_doc(doc),
                    "metadata": {
                        "tenant_id": meta.get("tenant_id"),
                        "document_id": meta.get("document_id"),
                        "source": meta.get("source", "unknown"),
                        "page": meta.get("page"),
                        "chunk_index": meta.get("chunk_index"),
                        "chunk_id": meta.get("chunk_id") or doc.id,
                        "img_id": meta.get("img_id"),
                        "image_id": meta.get("image_id"),
                        "image_url": meta.get("image_url"),
                        "bm25_score": float(final_score),
                        "bm25_score_raw": float(score),
                        "question_channel_score": float(question_channel_score),
                    },
                    "score": float(final_score),
                }
            )

        if not results:
            return []
        return heapq.nlargest(max(0, int(top_k or 0)), results, key=lambda x: float(x.get("score", 0.0) or 0.0))

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

    def _search_colbert_ann(
        self,
        query: str,
        top_k: int = 10,
        document_ids: list[UUID] | None = None,
        tenant_id: UUID | None = None,
        metadata_filter: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """
        Optional ColBERT-style ANN retrieval channel (production scaffold).

        Notes:
        - Uses the same BM25-scoped in-memory corpus as the index source.
        - Deterministic by default (no model downloads), with optional HF provider.
        - Persists index artifacts to disk when enabled (best-effort).
        """
        raw_query = str(query or "").strip()
        if not raw_query:
            return []
        if not bool(getattr(settings, "COLBERT_RETRIEVAL_ENABLED", False)):
            return []

        tenant_uuid: UUID | None = tenant_id
        if tenant_uuid is None:
            try:
                tenant_uuid = UUID(str(getattr(settings, "DEFAULT_TENANT_ID", "") or ""))
            except (TypeError, ValueError, AttributeError):
                tenant_uuid = None
        if tenant_uuid is None:
            return []

        dataset_scope_id: UUID | None = None
        if self.dataset_id is not None and not (document_ids or []):
            dataset_scope_id = self.dataset_id

        cache_key = self._bm25_scope_key(tenant_id=tenant_uuid, dataset_id=dataset_scope_id, document_ids=document_ids)
        docs = self._bm25_docs.get(cache_key) or []
        if not docs:
            return []

        from app.rag.retrieval.colbert_ann import (
            ColbertAnnIndexStore,
            build_colbert_provider_config,
            get_dense_embedder,
            resolve_colbert_ann_provider_capability,
            topk_cosine_scores,
        )

        # Provider readiness gate with deterministic fallback diagnostics.
        try:
            max_docs = int(getattr(settings, "COLBERT_RETRIEVAL_MAX_DOCS", 0) or 0)
        except (TypeError, ValueError, AttributeError):
            max_docs = 0
        requested_provider = str(getattr(settings, "COLBERT_RETRIEVAL_PROVIDER", "deterministic") or "deterministic").strip().lower()
        readiness = resolve_colbert_ann_provider_capability(
            colbert_enabled=bool(getattr(settings, "COLBERT_RETRIEVAL_ENABLED", False)),
            requested_provider=requested_provider,
            model_name=str(getattr(settings, "COLBERT_RETRIEVAL_MODEL_NAME", "") or ""),
            device=str(getattr(settings, "COLBERT_RETRIEVAL_DEVICE", "cpu") or "cpu"),
            docs_count=int(len(docs or [])),
            max_docs=int(max_docs),
        )
        try:
            if isinstance(self._last_channel_metrics, dict):
                box = self._last_channel_metrics.get("colbert_ann")
                if not isinstance(box, dict):
                    box = {}
                    self._last_channel_metrics["colbert_ann"] = box
                box["readiness"] = dict(readiness or {})
        except Exception as exc:
            logger.debug("Ignoring non-critical retriever fallback failure: %s", exc)

        if str(readiness.get("reason") or "") == "too_many_docs":
            try:
                if isinstance(self._last_channel_metrics, dict):
                    box = self._last_channel_metrics.get("colbert_ann")
                    if not isinstance(box, dict):
                        box = {}
                        self._last_channel_metrics["colbert_ann"] = box
                    box["skipped_reason"] = "too_many_docs"
                    box["docs_n"] = int(len(docs or []))
                    box["max_docs"] = int(max_docs)
            except Exception as exc:
                logger.debug("Ignoring non-critical retriever fallback failure: %s", exc)
            # Free any cached index for this scope to keep memory bounded.
            try:
                self._colbert_index_cache.pop(cache_key, None)
            except Exception as exc:
                logger.debug("Ignoring non-critical retriever fallback failure: %s", exc)
            return []

        provider = str(readiness.get("effective_provider") or "deterministic").strip().lower() or "deterministic"
        if not bool(readiness.get("ready", False)):
            try:
                if isinstance(self._last_channel_metrics, dict):
                    box = self._last_channel_metrics.get("colbert_ann")
                    if not isinstance(box, dict):
                        box = {}
                        self._last_channel_metrics["colbert_ann"] = box
                    box["skipped_reason"] = "provider_unready"
            except Exception as exc:
                logger.debug("Ignoring non-critical retriever fallback failure: %s", exc)
            return []

        provider_config = build_colbert_provider_config(
            provider=provider,
            model_name=str(getattr(settings, "COLBERT_RETRIEVAL_MODEL_NAME", "") or ""),
            device=str(getattr(settings, "COLBERT_RETRIEVAL_DEVICE", "cpu") or "cpu"),
            batch_size=int(getattr(settings, "COLBERT_RETRIEVAL_BATCH_SIZE", 16) or 16),
            max_length=int(getattr(settings, "COLBERT_RETRIEVAL_MAX_LENGTH", 256) or 256),
            deterministic_dim=int(getattr(settings, "COLBERT_RETRIEVAL_EMBED_DIM", 64) or 64),
        )

        expected_fp = self._colbert_corpus_fingerprint(docs)

        index = self._colbert_index_cache.get(cache_key)
        try:
            index_ok = (
                index is not None
                and str(getattr(index, "corpus_fingerprint", "") or "") == str(expected_fp or "")
                and dict(getattr(index, "provider_config", {}) or {}) == dict(provider_config)
            )
        except (TypeError, ValueError, AttributeError):
            index_ok = False

        if not index_ok and bool(getattr(settings, "COLBERT_RETRIEVAL_INDEX_PERSIST_ENABLED", True)):
            try:
                store = ColbertAnnIndexStore(base_dir=str(getattr(settings, "COLBERT_RETRIEVAL_INDEX_DIR", COLBERT_INDEX_DIR_FALLBACK) or ""))
                loaded = store.load(cache_key=cache_key, provider_config=provider_config, expected_fingerprint=expected_fp)
                if loaded is not None:
                    index = loaded
                    self._colbert_index_cache[cache_key] = loaded
                    index_ok = True
            except Exception as exc:
                _log_retriever_fallback('_search_colbert_ann', exc)
                index_ok = False

        if not index_ok:
            try:
                with self._get_colbert_build_lock(cache_key):
                    index = self._colbert_index_cache.get(cache_key)
                    try:
                        index_ok = (
                            index is not None
                            and str(getattr(index, "corpus_fingerprint", "") or "") == str(expected_fp or "")
                            and dict(getattr(index, "provider_config", {}) or {}) == dict(provider_config)
                        )
                    except (TypeError, ValueError, AttributeError):
                        index_ok = False

                    if not index_ok:
                        self._build_colbert_index(cache_key=cache_key, docs=docs)
                        index = self._colbert_index_cache.get(cache_key)
                        index_ok = index is not None
            except Exception as exc:
                _log_retriever_fallback('_search_colbert_ann', exc)
                index_ok = False
                index = self._colbert_index_cache.get(cache_key)

        if not index_ok or index is None:
            return []

        embedder = get_dense_embedder(
            provider=provider,
            model_name=str(getattr(settings, "COLBERT_RETRIEVAL_MODEL_NAME", "") or ""),
            device=str(getattr(settings, "COLBERT_RETRIEVAL_DEVICE", "cpu") or "cpu"),
            batch_size=int(getattr(settings, "COLBERT_RETRIEVAL_BATCH_SIZE", 16) or 16),
            max_length=int(getattr(settings, "COLBERT_RETRIEVAL_MAX_LENGTH", 256) or 256),
            deterministic_dim=int(getattr(settings, "COLBERT_RETRIEVAL_EMBED_DIM", 64) or 64),
        )
        q_mat = embedder.encode_batch([raw_query])
        try:
            q_vec = q_mat[0]
        except (TypeError, ValueError, AttributeError):
            return []

        doc_vecs = getattr(index, "vectors", None)
        doc_ids = list(getattr(index, "doc_ids", []) or [])
        if doc_vecs is None or not doc_ids:
            return []

        scored = topk_cosine_scores(query_vec=q_vec, doc_vecs=doc_vecs, k=max(0, int(top_k or 0)))
        if not scored:
            return []

        doc_by_id: dict[str, Document] = {str(d.id): d for d in docs if d is not None and d.id is not None}
        allowed_ids = {str(doc_id) for doc_id in document_ids} if document_ids else None

        results: list[dict[str, Any]] = []
        for idx, score in scored:
            if idx < 0 or idx >= len(doc_ids):
                continue
            doc_id = str(doc_ids[int(idx)])
            doc = doc_by_id.get(doc_id)
            if doc is None:
                continue
            meta = dict(doc.metadata or {})
            if allowed_ids and str(meta.get("document_id")) not in allowed_ids:
                continue
            if metadata_filter and self.metadata_filter_enabled:
                if not self._match_metadata_filter(meta, metadata_filter):
                    continue

            # Keep provenance stable and low-cardinality: expose score, but avoid embedding details.
            meta.setdefault("chunk_id", doc_id)
            meta["colbert_score"] = float(score)

            results.append(
                {
                    "chunk_id": doc_id,
                    "content": self._result_content_from_doc(doc),
                    "metadata": meta,
                    "score": float(score),
                }
            )

        if not results:
            return []
        return results

    def _search_sparse(
        self,
        query: str,
        top_k: int = 10,
        document_ids: list[UUID] | None = None,
        tenant_id: UUID | None = None,
        metadata_filter: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """
        Optional sparse retrieval channel (SPLADE-style scaffolding).

        - Uses the same BM25-scoped in-memory corpus as the sparse index source.
        - Uses a deterministic encoder by default (no model downloads).
        """
        raw_query = str(query or "").strip()
        if not raw_query:
            return []
        if not self._effective_sparse_enabled():
            return []

        tenant_uuid: UUID | None = tenant_id
        if tenant_uuid is None:
            try:
                tenant_uuid = UUID(str(getattr(settings, "DEFAULT_TENANT_ID", "") or ""))
            except (TypeError, ValueError, AttributeError):
                tenant_uuid = None
        if tenant_uuid is None:
            return []

        provider_status = self._resolve_sparse_provider_status(sparse_enabled=True)
        provider = str(provider_status.get("effective_provider") or "deterministic").strip().lower() or "deterministic"
        search_t0 = time.perf_counter()
        outcome = "error"
        candidates_count = 0
        reason = str(provider_status.get("reason") or "none")

        from app.rag.retrieval.sparse_prometheus_metrics import (  # local import: optional dependency
            observe_sparse_index_load,
            observe_sparse_search,
        )

        try:
            dataset_scope_id: UUID | None = None
            if self.dataset_id is not None and not (document_ids or []):
                dataset_scope_id = self.dataset_id

            # Align with BM25 scope so we reuse the same corpus and caching semantics.
            cache_key = self._bm25_scope_key(tenant_id=tenant_uuid, dataset_id=dataset_scope_id, document_ids=document_ids)
            docs = self._bm25_docs.get(cache_key) or []
            if not docs:
                outcome = "skipped"
                reason = "scope_empty"
                return []
            sparse_index_version_token = self._resolve_candidate_cache_corpus_token(
                tenant_id=tenant_uuid,
                document_ids=document_ids,
            )

            from app.rag.retrieval.sparse import (
                SparseIndexStore,
                build_sparse_provider_config,
                get_sparse_encoder,
                parse_synonyms,
                topk_scores,
            )

            synonyms_raw = str(getattr(settings, "SPARSE_RETRIEVAL_SYNONYMS", "") or "")
            synonyms = parse_synonyms(synonyms_raw) if synonyms_raw.strip() else {}
            provider_config = build_sparse_provider_config(
                provider=provider,
                synonyms_raw=synonyms_raw,
                model_name=str(getattr(settings, "SPARSE_SPLADE_MODEL_NAME", "") or ""),
                device=str(getattr(settings, "SPARSE_SPLADE_DEVICE", "cpu") or "cpu"),
                batch_size=int(getattr(settings, "SPARSE_SPLADE_BATCH_SIZE", 8) or 8),
                max_length=int(getattr(settings, "SPARSE_SPLADE_MAX_LENGTH", 256) or 256),
                top_k=int(getattr(settings, "SPARSE_SPLADE_TOP_K", 128) or 128),
                min_weight=float(getattr(settings, "SPARSE_SPLADE_MIN_WEIGHT", 0.0) or 0.0),
            )

            # Lazy-load persisted sparse vectors if needed (best-effort; robust across restarts).
            sparse_vecs = self._sparse_doc_vectors.get(cache_key) or {}
            had_index_load_error = False
            if len(sparse_vecs) != len(docs):
                if bool(getattr(settings, "SPARSE_RETRIEVAL_INDEX_PERSIST_ENABLED", True)):
                    load_outcome = "miss"
                    try:
                        fp = self._sparse_corpus_fingerprint(docs)
                        store = SparseIndexStore(
                            base_dir=str(getattr(settings, "SPARSE_RETRIEVAL_INDEX_DIR", SPARSE_INDEX_DIR_FALLBACK) or "")
                        )
                        loaded = store.load(
                            cache_key=cache_key,
                            provider_config=provider_config,
                            expected_fingerprint=fp,
                            expected_version_token=str(sparse_index_version_token or "").strip(),
                        )
                        if loaded:
                            sparse_vecs = loaded
                            self._sparse_doc_vectors[cache_key] = sparse_vecs
                            load_outcome = "hit"
                    except Exception as exc:
                        _log_retriever_fallback('_search_sparse', exc)
                        load_outcome = "error"
                        had_index_load_error = True
                    observe_sparse_index_load(provider=provider, outcome=load_outcome)
                else:
                    observe_sparse_index_load(provider=provider, outcome="skipped")

            had_index_build_error = False
            if len(sparse_vecs) != len(docs):
                try:
                    with self._get_sparse_build_lock(cache_key):
                        sparse_vecs = self._sparse_doc_vectors.get(cache_key) or {}
                        if len(sparse_vecs) != len(docs):
                            self._build_sparse_index(
                                cache_key=cache_key,
                                docs=docs,
                                version_token=sparse_index_version_token,
                            )
                            sparse_vecs = self._sparse_doc_vectors.get(cache_key) or {}
                except Exception as exc:
                    _log_retriever_fallback('_search_sparse', exc)
                    had_index_build_error = True
                    sparse_vecs = self._sparse_doc_vectors.get(cache_key) or {}

            if reason == "none" and had_index_load_error:
                reason = "index_load_error"
            if reason == "none" and had_index_build_error and len(sparse_vecs) != len(docs):
                reason = "index_build_failed"

            encoder = get_sparse_encoder(
                provider=provider,
                synonyms=synonyms,
                synonyms_raw=synonyms_raw,
                model_name=str(getattr(settings, "SPARSE_SPLADE_MODEL_NAME", "") or ""),
                device=str(getattr(settings, "SPARSE_SPLADE_DEVICE", "cpu") or "cpu"),
                batch_size=int(getattr(settings, "SPARSE_SPLADE_BATCH_SIZE", 8) or 8),
                max_length=int(getattr(settings, "SPARSE_SPLADE_MAX_LENGTH", 256) or 256),
                top_k=int(getattr(settings, "SPARSE_SPLADE_TOP_K", 128) or 128),
                min_weight=float(getattr(settings, "SPARSE_SPLADE_MIN_WEIGHT", 0.0) or 0.0),
            )
            q_raw = encoder.encode_batch([raw_query])[0]
            if isinstance(q_raw, SparseVector):
                q_vec = q_raw
            elif isinstance(q_raw, dict):
                q_vec = SparseVector(weights={str(k): float(v) for k, v in q_raw.items() if k is not None and v is not None})
            else:
                q_vec = SparseVector(weights={})

            scored = topk_scores(query_vec=q_vec, docs=sparse_vecs, k=max(0, int(top_k or 0)))
            if not scored:
                outcome = "empty"
                if reason == "none":
                    reason = "no_candidates"
                return []

            doc_by_id: dict[str, Document] = {str(d.id): d for d in docs if d is not None and d.id is not None}
            allowed_ids = {str(doc_id) for doc_id in document_ids} if document_ids else None

            results: list[dict[str, Any]] = []
            for doc_id, score in scored:
                doc = doc_by_id.get(str(doc_id))
                if doc is None:
                    continue
                meta = doc.metadata or {}
                if allowed_ids and str(meta.get("document_id")) not in allowed_ids:
                    continue
                if metadata_filter and self.metadata_filter_enabled:
                    if not self._match_metadata_filter(meta, metadata_filter):
                        continue
                results.append(
                    {
                        "chunk_id": doc.id,
                        "content": self._result_content_from_doc(doc),
                        "metadata": {
                            "tenant_id": meta.get("tenant_id"),
                            "document_id": meta.get("document_id"),
                            "source": meta.get("source", "unknown"),
                            "page": meta.get("page"),
                            "chunk_index": meta.get("chunk_index"),
                            "chunk_id": meta.get("chunk_id") or doc.id,
                            "img_id": meta.get("img_id"),
                            "image_id": meta.get("image_id"),
                            "image_url": meta.get("image_url"),
                            "sparse_score": float(score),
                        },
                        "score": float(score),
                    }
                )

            if not results:
                outcome = "empty"
                if reason == "none":
                    reason = "no_candidates"
                return []
            candidates_count = len(results)
            outcome = "ok"
            return heapq.nlargest(max(0, int(top_k or 0)), results, key=lambda x: float(x.get("score", 0.0) or 0.0))
        except Exception as exc:
            _log_retriever_fallback('_search_sparse', exc)
            outcome = "error"
            if reason == "none":
                reason = "exception"
            raise
        finally:
            try:
                self._last_sparse_provider_status = {
                    **provider_status,
                    "effective_provider": provider,
                    "status": str(provider_status.get("status") or "ready"),
                    "outcome": outcome,
                    "reason": reason,
                    "candidates": int(candidates_count or 0),
                }
            except (TypeError, ValueError, AttributeError):
                self._last_sparse_provider_status = {}
            observe_sparse_search(
                provider=provider,
                outcome=outcome,
                duration_sec=(time.perf_counter() - search_t0),
                candidates_count=candidates_count,
                reason=reason,
            )

    def _search_lexical_db(  # noqa: PLR0915
        self,
        *,
        query: str,
        top_k: int = 10,
        document_ids: list[UUID] | None = None,
        tenant_id: UUID | None = None,
        metadata_filter: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """
        Persistent lexical retrieval backed by the primary Postgres DB.

        Intended as a "last mile" safety net for false negatives (numbers, codes, exact phrases)
        when dense retrieval or in-memory BM25 miss.

        Implementation:
        - Full-text search: websearch_to_tsquery + ts_rank_cd (fast with a GIN tsvector index)
        - Optional: pg_trgm similarity fallback for short / code-like queries (fast with a trigram index)

        Returns dicts with raw `score` values; downstream fusion normalizes.
        """
        raw_query = str(query or "").strip()
        if not raw_query:
            return []
        if not bool(getattr(settings, "LEXICAL_DB_ENABLED", True)):
            return []

        tenant_uuid: UUID | None = tenant_id
        if tenant_uuid is None:
            try:
                tenant_uuid = UUID(str(getattr(settings, "DEFAULT_TENANT_ID", "") or ""))
            except (TypeError, ValueError, AttributeError):
                tenant_uuid = None
        if tenant_uuid is None:
            return []

        # Best-effort: extract dataset scope from the metadata filter so we can push it down via join.
        dataset_uuid: UUID | None = None
        dataset_str: str | None = None
        if isinstance(metadata_filter, dict):
            ds_raw = metadata_filter.get("dataset_id")
            if isinstance(ds_raw, str) and ds_raw.strip():
                dataset_str = ds_raw.strip()
                try:
                    dataset_uuid = UUID(dataset_str)
                except (TypeError, ValueError, AttributeError):
                    dataset_uuid = None

        # Config knobs (keep safe defaults even if not present in Settings yet).
        fts_config = str(getattr(settings, "LEXICAL_DB_FTS_CONFIG", "simple") or "simple").strip() or "simple"
        fetch_mult = int(getattr(settings, "LEXICAL_DB_FETCH_MULTIPLIER", 4) or 4)
        fetch_mult = max(1, fetch_mult)
        fetch_cap = int(getattr(settings, "LEXICAL_DB_MAX_CANDIDATES", 200) or 200)
        fetch_cap = max(10, fetch_cap)
        want_trgm = bool(getattr(settings, "LEXICAL_DB_TRGM_ENABLED", True))
        trgm_min_chars = int(getattr(settings, "LEXICAL_DB_TRGM_MIN_QUERY_CHARS", 3) or 3)
        trgm_min_chars = max(1, trgm_min_chars)

        limit = max(0, int(top_k or 0))
        if limit <= 0:
            return []
        fetch_k = min(fetch_cap, max(limit, limit * fetch_mult))

        db = SessionLocal()
        try:
            bind = db.get_bind()
            if not bind or getattr(getattr(bind, "dialect", None), "name", "") != "postgresql":
                return []

            def _base_query():
                q = (
                    db.query(
                        DocumentChunk.id,
                        DocumentChunk.content,
                        DocumentChunk.doc_metadata,
                        DocumentChunk.tenant_id,
                        DocumentChunk.document_id,
                        DocumentChunk.chunk_index,
                        DocumentChunk.page_number,
                    )
                    .join(DBDocument, DocumentChunk.document_id == DBDocument.id)
                    .filter(DBDocument.status == "completed")
                    .filter(DBDocument.publication_status == "published")
                    .filter(DBDocument.archived_at.is_(None))
                    .filter(DBDocument.disabled_at.is_(None))
                    .filter(DocumentChunk.disabled_at.is_(None))
                    .filter(DocumentChunk.tenant_id == tenant_uuid)
                )
                if dataset_uuid is not None:
                    q = q.filter(DBDocument.dataset_id == dataset_uuid)
                if document_ids:
                    q = q.filter(DocumentChunk.document_id.in_(document_ids))
                return q

            results_by_id: dict[str, dict[str, Any]] = {}

            # 1) Full-text search (FTS)
            try:
                vector = func.to_tsvector(fts_config, DocumentChunk.content)
                tsq = func.websearch_to_tsquery(fts_config, raw_query)
                rank = func.ts_rank_cd(vector, tsq).label("fts_rank")
                q1 = (
                    _base_query()
                    .add_columns(rank)
                    .filter(vector.op("@@")(tsq))
                    .order_by(rank.desc())
                    .limit(fetch_k)
                )
                for row in q1.all():
                    try:
                        (
                            chunk_id,
                            content,
                            doc_metadata,
                            tenant_uuid_row,
                            document_uuid_row,
                            chunk_index,
                            page_number,
                            fts_rank,
                        ) = row
                    except (TypeError, ValueError, AttributeError):
                        continue

                    cid = str(chunk_id)
                    meta = dict(doc_metadata or {})
                    meta.setdefault("tenant_id", str(tenant_uuid_row))
                    meta.setdefault("document_id", str(document_uuid_row))
                    meta.setdefault("chunk_index", int(chunk_index) if chunk_index is not None else None)
                    meta.setdefault("chunk_id", cid)
                    meta.setdefault("source", meta.get("source", "unknown"))
                    if dataset_str:
                        meta.setdefault("dataset_id", dataset_str)
                    if page_number is not None and not meta.get("page"):
                        meta["page"] = page_number
                    meta.setdefault("lexical_method", "fts")
                    meta.setdefault("lexical_score_raw", float(fts_rank or 0.0))

                    if metadata_filter and not self._match_metadata_filter(meta, metadata_filter):
                        continue

                    results_by_id[cid] = {
                        "chunk_id": cid,
                        "content": content or "",
                        "metadata": meta,
                        "score": float(fts_rank or 0.0),
                    }
            except Exception as exc:
                logger.debug("Lexical FTS query failed: %s", exc)

            # 1b) Plain FTS fallback (plainto_tsquery)
            #
            # `websearch_to_tsquery` is convenient for natural language, but it may interpret
            # code-like inputs (paths, hyphenated tokens, etc.) as operators and return no hits.
            # When the websearch query yields no results, fall back to a "plain" tsquery.
            if not results_by_id:
                try:
                    vector = func.to_tsvector(fts_config, DocumentChunk.content)
                    tsq = func.plainto_tsquery(fts_config, raw_query)
                    rank = func.ts_rank_cd(vector, tsq).label("fts_rank")
                    q1_plain = (
                        _base_query()
                        .add_columns(rank)
                        .filter(vector.op("@@")(tsq))
                        .order_by(rank.desc())
                        .limit(fetch_k)
                    )
                    for row in q1_plain.all():
                        try:
                            (
                                chunk_id,
                                content,
                                doc_metadata,
                                tenant_uuid_row,
                                document_uuid_row,
                                chunk_index,
                                page_number,
                                fts_rank,
                            ) = row
                        except (TypeError, ValueError, AttributeError):
                            continue

                        cid = str(chunk_id)
                        meta = dict(doc_metadata or {})
                        meta.setdefault("tenant_id", str(tenant_uuid_row))
                        meta.setdefault("document_id", str(document_uuid_row))
                        meta.setdefault("chunk_index", int(chunk_index) if chunk_index is not None else None)
                        meta.setdefault("chunk_id", cid)
                        meta.setdefault("source", meta.get("source", "unknown"))
                        if dataset_str:
                            meta.setdefault("dataset_id", dataset_str)
                        if page_number is not None and not meta.get("page"):
                            meta["page"] = page_number
                        meta.setdefault("lexical_method", "fts_plain")
                        meta.setdefault("lexical_score_raw", float(fts_rank or 0.0))

                        if metadata_filter and not self._match_metadata_filter(meta, metadata_filter):
                            continue

                        results_by_id[cid] = {
                            "chunk_id": cid,
                            "content": content or "",
                            "metadata": meta,
                            "score": float(fts_rank or 0.0),
                        }
                except Exception as exc:
                    logger.debug("Lexical plain FTS query failed: %s", exc)

            # 2) Trigram fallback (pg_trgm)
            if want_trgm and len(raw_query) >= trgm_min_chars:
                pg_trgm_available = self._lexical_pg_trgm_available
                if pg_trgm_available is None:
                    try:
                        row = db.execute(text("SELECT 1 FROM pg_extension WHERE extname='pg_trgm' LIMIT 1;")).first()
                        pg_trgm_available = bool(row)
                    except Exception as exc:
                        _log_retriever_fallback('_search_lexical_db', exc)
                        pg_trgm_available = False
                    self._lexical_pg_trgm_available = pg_trgm_available

                if pg_trgm_available:
                    try:
                        sim = func.similarity(DocumentChunk.content, raw_query).label("trgm_sim")
                        q2 = (
                            _base_query()
                            .add_columns(sim)
                            .filter(DocumentChunk.content.op("%")(raw_query))
                            .order_by(sim.desc())
                            .limit(fetch_k)
                        )
                        for row in q2.all():
                            try:
                                (
                                    chunk_id,
                                    content,
                                    doc_metadata,
                                    tenant_uuid_row,
                                    document_uuid_row,
                                    chunk_index,
                                    page_number,
                                    trgm_sim,
                                ) = row
                            except (TypeError, ValueError, AttributeError):
                                continue

                            cid = str(chunk_id)
                            score = float(trgm_sim or 0.0)
                            meta = dict(doc_metadata or {})
                            meta.setdefault("tenant_id", str(tenant_uuid_row))
                            meta.setdefault("document_id", str(document_uuid_row))
                            meta.setdefault("chunk_index", int(chunk_index) if chunk_index is not None else None)
                            meta.setdefault("chunk_id", cid)
                            meta.setdefault("source", meta.get("source", "unknown"))
                            if dataset_str:
                                meta.setdefault("dataset_id", dataset_str)
                            if page_number is not None and not meta.get("page"):
                                meta["page"] = page_number
                            meta.setdefault("lexical_method", "trgm")
                            meta.setdefault("lexical_score_raw", score)

                            if metadata_filter and not self._match_metadata_filter(meta, metadata_filter):
                                continue

                            existing = results_by_id.get(cid)
                            if existing is None or float(existing.get("score", 0.0) or 0.0) < score:
                                results_by_id[cid] = {
                                    "chunk_id": cid,
                                    "content": content or "",
                                    "metadata": meta,
                                    "score": score,
                                }
                    except Exception as exc:
                        logger.debug("Lexical trigram query failed: %s", exc)

            if not results_by_id:
                return []
            merged = list(results_by_id.values())
            merged.sort(key=lambda x: float(x.get("score", 0.0) or 0.0), reverse=True)
            return merged[:limit]
        finally:
            try:
                db.close()
            except Exception as exc:
                logger.debug("Ignoring non-critical retriever fallback failure: %s", exc)

    def _hybrid_search(
        self,
        query: str,
        *,
        options: HybridSearchOptions | None = None,
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
        }
        self._last_channel_metrics = channel_metrics
        # Reset per-call diversity caps meta to avoid stale fields on cache-hit/early-return paths.
        self._last_diversity_caps = {}

        vector_elapsed_ms = 0.0
        colbert_elapsed_ms = 0.0
        bm25_elapsed_ms = 0.0
        lexical_elapsed_ms = 0.0
        colbert_used = False
        colbert_candidates = 0
        colpali_results: list[dict[str, Any]] = []
        want_colpali = False
        colpali_reason = "disabled"
        tenant_uuid = tenant_id or self.tenant_id
        embedding_runtime = self._resolve_embedding_runtime(tenant_id=tenant_uuid)
        embedding_space = str(embedding_runtime.embedding_space_hash or "").strip()

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
        if self.dataset_id is not None:
            ds_val = str(self.dataset_id)
            if isinstance(full_metadata_filter, dict) and full_metadata_filter:
                full_metadata_filter = dict(full_metadata_filter)
                full_metadata_filter.setdefault("dataset_id", ds_val)
            else:
                full_metadata_filter = {"dataset_id": ds_val}
        bm25_filter: dict[str, Any] | None = None
        vector_filter: dict[str, Any] | None = None
        if full_metadata_filter and isinstance(full_metadata_filter, dict):
            bm25_filter = {
                k: v
                for k, v in full_metadata_filter.items()
                if isinstance(k, str) and not str(k).startswith("document_user.")
            }
            # Milvus document vectors support only a subset of scalar fields.
            # Keep keys top-level only (no dotted paths) and map common aliases.
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
            for k, v in bm25_filter.items():
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

            # Embedding space guard pushdown (backward compatible): include both the current
            # embedding space and the empty-string legacy value.
            try:
                space = embedding_space
            except (TypeError, ValueError, AttributeError):
                space = ""
            if space and "embedding_space_hash" not in vf:
                vf["embedding_space_hash"] = {"$in": [space, ""]}
            vector_filter = vf or None

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
        cache_eligible = bool(getattr(settings, "RETRIEVAL_CANDIDATE_CACHE_ENABLED", False))

        semantic_cache_eligible = bool(getattr(settings, "SEMANTIC_CACHE_ENABLED", False))
        if embedding_runtime.dataset_scoped:
            # Semantic cache currently embeds with the global adapter. Avoid cross-space hits for dataset-scoped embeddings.
            semantic_cache_eligible = False
        semantic_cache_hit = False
        semantic_cached = None

        corpus_cache_token: str | None = None
        account_id0 = (self.account_id or "").strip()
        dataset_id0 = str(self.dataset_id) if self.dataset_id is not None else None
        pipeline_key = embedding_space or None
        doc_ids = [str(d) for d in (document_ids or [])]

        cache_meta: dict[str, Any] = {
            "enabled": bool(cache_eligible),
            "backend": "redis",
            "hit": False,
            "semantic": {
                "enabled": bool(semantic_cache_eligible),
                "backend": "milvus+redis",
                "hit": False,
            },
        }
        if isinstance(self._last_channel_metrics, dict):
            self._last_channel_metrics["cache"] = cache_meta

        # Shared scope checks (fail closed).
        if tenant_uuid is None:
            cache_eligible = False
            semantic_cache_eligible = False
            cache_meta["skip_reason"] = "missing_tenant"
            cache_meta["semantic"]["skip_reason"] = "missing_tenant"
        elif not account_id0:
            cache_eligible = False
            semantic_cache_eligible = False
            cache_meta["skip_reason"] = "missing_account"
            cache_meta["semantic"]["skip_reason"] = "missing_account"
        elif not document_ids and self.dataset_id is None:
            cache_eligible = False
            semantic_cache_eligible = False
            cache_meta["skip_reason"] = "missing_scope"
            cache_meta["semantic"]["skip_reason"] = "missing_scope"

        if cache_eligible:
            ttl = int(getattr(settings, "RETRIEVAL_CANDIDATE_CACHE_TTL_SEC", 0) or 0)
            if ttl <= 0:
                cache_eligible = False
                cache_meta["skip_reason"] = "ttl_zero"

        if semantic_cache_eligible:
            ttl = int(getattr(settings, "SEMANTIC_CACHE_TTL_SEC", 0) or 0)
            if ttl <= 0:
                semantic_cache_eligible = False
                cache_meta["semantic"]["skip_reason"] = "ttl_zero"

        if cache_eligible or semantic_cache_eligible:
            try:
                corpus_cache_token = self._resolve_candidate_cache_corpus_token(
                    tenant_id=tenant_uuid,
                    document_ids=document_ids,
                )
            except Exception as exc:
                _log_retriever_fallback('_hybrid_search', exc)
                corpus_cache_token = None

            if not corpus_cache_token:
                if cache_eligible:
                    cache_eligible = False
                    cache_meta["skip_reason"] = "missing_corpus_cache_token"
                if semantic_cache_eligible:
                    semantic_cache_eligible = False
                    cache_meta["semantic"]["skip_reason"] = "missing_corpus_cache_token"

        if cache_eligible:
            try:
                cache_key = build_retrieval_candidate_cache_key(
                    tenant_id=str(tenant_uuid),
                    account_id=account_id0,
                    dataset_id=dataset_id0,
                    pipeline_key=pipeline_key,
                    corpus_cache_token=corpus_cache_token,
                    query=query,
                    top_k=int(top_k or 0),
                    score_threshold=float(score_threshold or 0.0),
                    retrieval_mode=retrieval_mode,
                    metadata_filter=full_metadata_filter if isinstance(full_metadata_filter, dict) else None,
                    document_ids=doc_ids,
                )
                cached = get_cached_retrieval_candidates(cache_key) if cache_key else None
            except Exception as exc:
                _log_retriever_fallback('_hybrid_search', exc)
                cached = None
                cache_eligible = False
                cache_meta["skip_reason"] = "lookup_error"

        if cached:
            cache_hit = True
            try:
                if isinstance(self._last_channel_metrics, dict):
                    self._last_channel_metrics.setdefault("cache", {})  # type: ignore[call-arg]
                    self._last_channel_metrics["cache"]["hit"] = True
                    self._last_channel_metrics["cache"].pop("skip_reason", None)
            except Exception as exc:
                logger.debug("Ignoring non-critical retriever fallback failure: %s", exc)
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
                logger.debug("Ignoring non-critical retriever fallback failure: %s", exc)
            return semantic_cached[:top_k]

        emit_stream_event("event", {"message": "正在召回候选…"}, dedupe_key="retrieval.recall")

        # MMR mode needs more candidates for diversity selection
        fetch_k = top_k * 2
        if retrieval_mode == "mmr":
            fetch_k = top_k * max(1, mmr_fetch_k_multiplier)

        # 1) Vector retrieval
        vector_results: list[dict[str, Any]] = []
        if want_vector:
            vector_store = get_vector_store()
            try:
                search_kwargs = {
                    "query": query,
                    "top_k": fetch_k,
                    "score_threshold": score_threshold,
                    "document_ids": document_ids,
                    "tenant_id": tenant_id,
                }
                # Add metadata filter if supported and provided
                if vector_filter:
                    search_kwargs["metadata_filter"] = vector_filter

                t0 = time.perf_counter()
                try:
                    if embedding_runtime.dataset_scoped:
                        vector_results = self._search_dataset_scoped_vectors(
                            query=query,
                            top_k=fetch_k,
                            score_threshold=score_threshold,
                            document_ids=document_ids,
                            tenant_id=tenant_id,
                            metadata_filter=vector_filter,
                            embedding_runtime=embedding_runtime,
                        )
                    else:
                        vector_results = vector_store.search(**search_kwargs)
                finally:
                    vector_elapsed_ms += (time.perf_counter() - t0) * 1000
            except Exception as exc:
                logger.warning("Vector search failed: %s", exc)
                vector_results = []

        # Optional: ColBERT ANN fallback for vector retrieval.
        # This is opt-in and only runs when vector backend returns empty results.
        if want_vector and not vector_results and bool(getattr(settings, "COLBERT_RETRIEVAL_ENABLED", False)):
            try:
                t0 = time.perf_counter()
                try:
                    vector_results = self._search_colbert_ann(
                        query=query,
                        top_k=fetch_k,
                        document_ids=document_ids,
                        tenant_id=tenant_id,
                        metadata_filter=bm25_filter,
                    )
                    colbert_used = True
                    colbert_candidates = int(len(vector_results or []))
                finally:
                    delta_ms = (time.perf_counter() - t0) * 1000
                    vector_elapsed_ms += delta_ms
                    colbert_elapsed_ms += delta_ms
            except Exception as exc:
                logger.warning("ColBERT ANN search failed: %s", exc)
                vector_results = []

        bm25_results: list[dict[str, Any]] = []
        lexical_results: list[dict[str, Any]] = []
        lexical_run_reason = "not_run"
        lexical_hybrid_fallback_only = bool(getattr(settings, "LEXICAL_DB_HYBRID_FALLBACK_ONLY", True))
        if retrieval_mode == "keyword":
            if want_lexical:
                t0 = time.perf_counter()
                try:
                    lexical_results = self._search_lexical_db(
                        query=query,
                        top_k=fetch_k,
                        document_ids=document_ids,
                        tenant_id=tenant_id,
                        metadata_filter=bm25_filter,
                    )
                    lexical_run_reason = "keyword_primary"
                except Exception as exc:
                    logger.warning(LEXICAL_DB_SEARCH_FAILED_LOG, exc)
                    lexical_results = []
                    lexical_run_reason = "error"
                finally:
                    lexical_elapsed_ms += (time.perf_counter() - t0) * 1000
            if want_bm25:
                t0 = time.perf_counter()
                try:
                    bm25_results = self._search_bm25(
                        query=query,
                        top_k=fetch_k,
                        document_ids=document_ids,
                        tenant_id=tenant_id,
                        metadata_filter=bm25_filter,
                    )
                finally:
                    bm25_elapsed_ms += (time.perf_counter() - t0) * 1000
            elif not lexical_results and bm25_index_enabled:
                t0 = time.perf_counter()
                try:
                    bm25_results = self._search_bm25(
                        query=query,
                        top_k=fetch_k,
                        document_ids=document_ids,
                        tenant_id=tenant_id,
                        metadata_filter=bm25_filter,
                    )
                finally:
                    bm25_elapsed_ms += (time.perf_counter() - t0) * 1000
        else:
            # 2) BM25 retrieval
            if want_bm25:
                t0 = time.perf_counter()
                try:
                    bm25_results = self._search_bm25(
                        query=query,
                        top_k=fetch_k,
                        document_ids=document_ids,
                        tenant_id=tenant_id,
                        metadata_filter=bm25_filter,
                    )
                finally:
                    bm25_elapsed_ms += (time.perf_counter() - t0) * 1000

            # 2b) Persistent lexical fallback (Postgres FTS / pg_trgm).
            #
            # Hybrid/MMR usually already has dense vector + in-memory BM25 coverage.
            # Running pg_trgm on every query is expensive on large datasets, so keep it
            # as a recall safety net unless explicitly configured to run in parallel.
            primary_candidate_count = len(vector_results or []) + len(bm25_results or [])
            should_run_lexical = bool(want_lexical) and (
                not lexical_hybrid_fallback_only or primary_candidate_count < max(1, int(top_k or 0))
            )
            if should_run_lexical:
                t0 = time.perf_counter()
                try:
                    lexical_results = self._search_lexical_db(
                        query=query,
                        top_k=fetch_k,
                        document_ids=document_ids,
                        tenant_id=tenant_id,
                        metadata_filter=bm25_filter,
                    )
                    lexical_run_reason = "hybrid_parallel" if not lexical_hybrid_fallback_only else "hybrid_fallback"
                except Exception as exc:
                    logger.warning(LEXICAL_DB_SEARCH_FAILED_LOG, exc)
                    lexical_results = []
                    lexical_run_reason = "error"
                finally:
                    lexical_elapsed_ms += (time.perf_counter() - t0) * 1000
            elif want_lexical:
                lexical_run_reason = "skipped_primary_candidates_sufficient"

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
            try:
                sparse_results = self._search_sparse(
                    query=query,
                    top_k=fetch_k,
                    document_ids=document_ids,
                    tenant_id=tenant_id,
                    metadata_filter=bm25_filter,
                )
            except Exception as exc:
                logger.warning("Sparse search failed: %s", exc)
                sparse_results = []

        if want_colpali:
            try:
                colpali_results = self._search_colpali_retriever(
                    query=query,
                    top_k=fetch_k,
                    document_ids=document_ids,
                    tenant_id=tenant_id,
                    metadata_filter=bm25_filter,
                )
            except Exception as exc:
                logger.warning("ColPali retriever failed: %s", exc)
                colpali_results = []

        # Fallback: when single-channel mode fails, try the other channel.
        if retrieval_mode == "vector" and not vector_results:
            t0 = time.perf_counter()
            try:
                bm25_results = self._search_bm25(
                    query=query,
                    top_k=fetch_k,
                    document_ids=document_ids,
                    tenant_id=tenant_id,
                    metadata_filter=bm25_filter,
                )
            finally:
                bm25_elapsed_ms += (time.perf_counter() - t0) * 1000
            try:
                t0 = time.perf_counter()
                lexical_results = self._search_lexical_db(
                    query=query,
                    top_k=fetch_k,
                    document_ids=document_ids,
                    tenant_id=tenant_id,
                    metadata_filter=bm25_filter,
                )
                lexical_run_reason = "vector_fallback"
            except Exception as exc:
                logger.warning(LEXICAL_DB_SEARCH_FAILED_LOG, exc)
                lexical_results = []
                lexical_run_reason = "error"
            finally:
                lexical_elapsed_ms += (time.perf_counter() - t0) * 1000
            if want_sparse:
                try:
                    sparse_results = self._search_sparse(
                        query=query,
                        top_k=fetch_k,
                        document_ids=document_ids,
                        tenant_id=tenant_id,
                        metadata_filter=bm25_filter,
                    )
                except Exception as exc:
                    logger.warning("Sparse search failed: %s", exc)
                    sparse_results = []
        elif retrieval_mode == "keyword" and not bm25_results and not lexical_results and not sparse_results:
            vector_store = get_vector_store()
            try:
                fallback_kwargs = {
                    "query": query,
                    "top_k": fetch_k,
                    "score_threshold": score_threshold,
                    "document_ids": document_ids,
                    "tenant_id": tenant_id,
                }
                if vector_filter:
                    fallback_kwargs["metadata_filter"] = vector_filter
                t0 = time.perf_counter()
                try:
                    if embedding_runtime.dataset_scoped:
                        vector_results = self._search_dataset_scoped_vectors(
                            query=query,
                            top_k=fetch_k,
                            score_threshold=score_threshold,
                            document_ids=document_ids,
                            tenant_id=tenant_id,
                            metadata_filter=vector_filter,
                            embedding_runtime=embedding_runtime,
                        )
                    else:
                        vector_results = vector_store.search(**fallback_kwargs)
                finally:
                    vector_elapsed_ms += (time.perf_counter() - t0) * 1000
            except Exception as exc:
                logger.warning("Vector search failed: %s", exc)
                vector_results = []

        # Defense-in-depth: if Milvus/Vector backend cannot push down a huge document_ids filter,
        # enforce the scope client-side to preserve semantics.
        if vector_results and document_ids:
            allowed = {str(did) for did in document_ids if did is not None}
            if allowed:
                filtered_vec: list[dict[str, Any]] = []
                for r in vector_results:
                    meta = r.get("metadata") or {}
                    did = meta.get("document_id") or r.get("document_id")
                    if did is None:
                        continue
                    if str(did) in allowed:
                        filtered_vec.append(r)
                vector_results = filtered_vec

        # Try to fill in chunk_id for vector retrieval results (for citations / RAGAS contexts)
        if vector_results:
            if vector_filter:
                vector_results = [r for r in vector_results if self._match_metadata_filter((r.get("metadata") or {}), vector_filter)]
            tenant_key = self._tenant_key(tenant_id)
            lookup = self._chunk_id_lookup.get(tenant_key) or {}
            for r in vector_results:
                meta = r.get("metadata") or {}
                existing = r.get("chunk_id") or meta.get("chunk_id")
                if existing:
                    r["chunk_id"] = str(existing)
                    meta = dict(meta)
                    meta["chunk_id"] = str(existing)
                    r["metadata"] = meta
                    continue
                doc_id = meta.get("document_id")
                chunk_index = meta.get("chunk_index")
                if doc_id is None or chunk_index is None:
                    continue
                mapped = None
                doc_pipeline_key = meta.get("doc_pipeline_key")
                if doc_pipeline_key is not None:
                    mapped = lookup.get(f"{doc_pipeline_key}:{chunk_index}")
                if not mapped:
                    mapped = lookup.get(f"{doc_id}:{chunk_index}")
                if not mapped:
                    continue
                r["chunk_id"] = mapped
                meta["chunk_id"] = mapped
                r["metadata"] = meta

        # Per-query channel metrics (best-effort): used by evidence/debug endpoints.
        try:
            lexical_methods: Counter[str] = Counter()
            for r in lexical_results:
                meta = r.get("metadata") or {}
                m = str(meta.get("lexical_method") or "unknown").strip().lower() or "unknown"
                lexical_methods[m] += 1

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

            # Optional: ColBERT ANN fallback meta (PII-safe, low-cardinality).
            colbert_box = channel_metrics.get("colbert_ann")
            if not isinstance(colbert_box, dict):
                colbert_box = {}
            colbert_readiness = colbert_box.get("readiness") if isinstance(colbert_box.get("readiness"), dict) else {}
            colbert_box.update(
                {
                    "enabled": bool(getattr(settings, "COLBERT_RETRIEVAL_ENABLED", False)),
                    "used": bool(colbert_used),
                    "candidates": int(colbert_candidates or 0),
                    "provider": str(
                        (colbert_readiness.get("effective_provider") if isinstance(colbert_readiness, dict) else None)
                        or getattr(settings, "COLBERT_RETRIEVAL_PROVIDER", "")
                        or ""
                    ),
                }
            )
            channel_metrics["colbert_ann"] = colbert_box

            sparse_status = dict(self._last_sparse_provider_status or {})
            sparse_provider_status = {
                "requested_provider": str(sparse_status.get("requested_provider") or ""),
                "requested_provider_normalized": str(sparse_status.get("requested_provider_normalized") or ""),
                "effective_provider": str(
                    sparse_status.get("effective_provider")
                    or self.sparse_provider
                    or "deterministic"
                ),
                "provider_supported": bool(sparse_status.get("provider_supported", False)),
                "model_required": bool(sparse_status.get("model_required", False)),
                "model_configured": bool(sparse_status.get("model_configured", False)),
                "status": str(sparse_status.get("status") or ""),
                "reason": str(sparse_status.get("reason") or ""),
                "outcome": str(sparse_status.get("outcome") or ""),
            }

            channel_metrics.update(
                {
                    "retrieval_mode": retrieval_mode,
                    "fusion_strategy": str(self.fusion_strategy or ""),
                    "rrf_k": int(self.rrf_k or 0),
                    "fusion_weights": (
                        dict(
                            sorted(
                                (str(k), round(float(v), 6))
                                for k, v in (getattr(self, "fusion_weights", None) or {}).items()
                                if str(k or "").strip() and v is not None
                            )
                        )
                        if isinstance(getattr(self, "fusion_weights", None), dict) and getattr(self, "fusion_weights", None)
                        else None
                    ),
                    "vector_backend": str(getattr(settings, "VECTOR_BACKEND", "") or ""),
                    "vector": {
                        "enabled": bool(want_vector),
                        "candidates": len(vector_results or []),
                        "filter_applied": bool(vector_filter),
                    },
                    "bm25": {
                        "enabled": bool(want_bm25),
                        "candidates": len(bm25_results or []),
                        "index_enabled": bool(bm25_index_enabled),
                        "filter_applied": bool(bm25_filter),
                    },
                    "lexical_db": {
                        "enabled": bool(want_lexical) and bool(lexical_db_enabled),
                        "used": bool(lexical_results),
                        "candidates": len(lexical_results or []),
                        "run_reason": lexical_run_reason,
                        "hybrid_fallback_only": bool(lexical_hybrid_fallback_only),
                        "fts_config": str(getattr(settings, "LEXICAL_DB_FTS_CONFIG", "simple") or "simple"),
                        "trgm_enabled": bool(getattr(settings, "LEXICAL_DB_TRGM_ENABLED", True)),
                        "pg_trgm_available": self._lexical_pg_trgm_available,
                        "methods": dict(lexical_methods),
                    },
                    "colpali": {
                        "enabled": bool(want_colpali),
                        "used": bool(colpali_results),
                        "candidates": len(colpali_results or []),
                        "reason": colpali_reason,
                    },
                    "sparse": {
                        "enabled": bool(want_sparse),
                        "candidates": len(sparse_results or []),
                        "provider": str(
                            sparse_provider_status.get("effective_provider")
                            or self.sparse_provider
                            or "deterministic"
                        ),
                        "provider_status": sparse_provider_status,
                    },
                }
            )
            if keyword_strategy is not None:
                keyword_strategy["bm25_used"] = bool(bm25_results)
                keyword_strategy["lexical_db_used"] = bool(lexical_results)
                keyword_strategy["sparse_used"] = bool(sparse_results)
                channel_metrics["keyword_strategy"] = keyword_strategy
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
                logger.debug("Ignoring non-critical retriever fallback failure: %s", exc)

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

        try:
            if isinstance(self._last_channel_metrics, dict):
                self._last_channel_metrics["merged_pre_dedup"] = len(merged_results or [])
        except Exception as exc:
            logger.debug("Ignoring non-critical retriever fallback failure: %s", exc)

        merged_results = self._deduplicate_results(merged_results)

        try:
            if isinstance(self._last_channel_metrics, dict):
                self._last_channel_metrics["merged_post_dedup"] = len(merged_results or [])
        except Exception as exc:
            logger.debug("Ignoring non-critical retriever fallback failure: %s", exc)
        try:
            timing = channel_metrics.get("timing")
            if isinstance(timing, dict):
                timing["fusion_ms"] = round(float((time.perf_counter() - t_fusion0) * 1000), 2)
        except Exception as exc:
            logger.debug("Ignoring non-critical retriever fallback failure: %s", exc)

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
                        logger.debug("Ignoring non-critical retriever fallback failure: %s", exc)
                    if isinstance(self._last_channel_metrics, dict):
                        self._last_channel_metrics["merged_post_rerank"] = len(merged_results or [])
                else:
                    reranker = get_reranker(provider)

                    candidates: list[RerankCandidate] = []
                    id_to_doc: dict[str, dict[str, Any]] = {}
                    for doc in merged_results[:candidates_n]:
                        rid = self._result_key(doc)
                        text = (doc.get("content") or "").strip()
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
                            for rid in result.ordered_ids:
                                d = id_to_doc.get(rid)
                                if not d or rid in used:
                                    continue
                                used.add(rid)
                                new_doc = dict(d)
                                new_doc["retrieval_score"] = float(new_doc.get("score", 0.0) or 0.0)
                                if rid in result.score_map:
                                    new_doc["rerank_score"] = float(result.score_map[rid])
                                    new_doc["score"] = float(result.score_map[rid])
                                new_doc["reranker_provider"] = rerank_provider
                                new_doc["rerank_elapsed_sec"] = round(float(rerank_elapsed), 3)
                                new_doc["rerank_model_used"] = result.model_used
                                ordered.append(new_doc)

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
                logger.debug("Ignoring non-critical retriever fallback failure: %s", exc)

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
            logger.debug("Ignoring non-critical retriever fallback failure: %s", exc)

        before_diversity = len(merged_results or [])
        div_caps: dict[str, Any] = {}
        merged_results = self._apply_document_diversity(merged_results, top_k=top_k, stats=div_caps)
        self._last_diversity_caps = div_caps
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
            logger.debug("Ignoring non-critical retriever fallback failure: %s", exc)
        out = merged_results[:top_k]

        if cache_eligible and (not cache_hit) and cache_key and out:
            try:
                stored = bool(set_cached_retrieval_candidates(cache_key, out))
                if isinstance(self._last_channel_metrics, dict):
                    self._last_channel_metrics.setdefault("cache", {})  # type: ignore[call-arg]
                    self._last_channel_metrics["cache"]["store_ok"] = stored
            except Exception as exc:
                logger.debug("Ignoring non-critical retriever fallback failure: %s", exc)
        if semantic_cache_eligible and (not semantic_cache_hit) and corpus_cache_token and out:
            try:
                from app.services.semantic_cache import set_cached_semantic_payload

                stored = bool(
                    set_cached_semantic_payload(
                        tenant_id=str(tenant_uuid),
                        account_id=account_id0,
                        dataset_id=dataset_id0,
                        corpus_cache_token=str(corpus_cache_token),
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
                logger.debug("Ignoring non-critical retriever fallback failure: %s", exc)

        return out

    # ---- LangChain Retriever API ----

    def _enrich_results_with_db_metadata(
        self,
        results: list[dict[str, Any]],
        *,
        stats: dict[str, Any] | None = None,
        _stats: dict[str, Any] | None = None,
        metadata_filter_override: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """
        Vector store may return "trimmed" metadata (e.g., without img_id).
        Use chunk_id / (document_id, chunk_index) to look up DB and fill in key fields:
        - img_id: For MinIO image display
        - page/source: For context annotation (keeping consistent with DB)
        """
        if not results:
            return results

        stats0 = _stats if _stats is not None else stats
        if stats0 is not None:
            stats0.clear()
            stats0["input_results"] = len(results)
            stats0["filtered_orphaned"] = 0
            stats0["filtered_acl"] = 0
            stats0["filtered_dataset"] = 0
            stats0["filtered_not_ready"] = 0
            stats0["filtered_embedding_space"] = 0
            stats0["filtered_pipeline_version"] = 0
            stats0["filtered_metadata_filter"] = 0
            stats0["output_results"] = 0
            stats0["exception"] = None

        db = SessionLocal()
        try:
            tenant_filter = self.tenant_id
            account_id = (self.account_id or "").strip() or None
            dataset_filter = self.dataset_id
            embedding_space = self._resolve_embedding_runtime(
                tenant_id=tenant_filter,
            ).embedding_space_hash

            chunk_ids: list[UUID] = []
            # First collect existing chunk_ids (prefer using these for lookup)
            for r in results:
                cid = r.get("chunk_id")
                if not cid:
                    meta = r.get("metadata") or {}
                    cid = meta.get("chunk_id")
                if not cid:
                    continue
                try:
                    chunk_ids.append(UUID(str(cid)))
                except (TypeError, ValueError, AttributeError):
                    continue

            chunks_by_id: dict[str, DocumentChunk] = {}
            if chunk_ids:
                q = db.query(DocumentChunk).filter(DocumentChunk.id.in_(chunk_ids))
                if tenant_filter:
                    q = q.filter(DocumentChunk.tenant_id == tenant_filter)
                for ck in q.all():
                    chunks_by_id[str(ck.id)] = ck

            # Batch lookup missing chunk_id by (document_id, chunk_index) to avoid N+1 queries.
            missing_pairs: set[tuple[UUID, int]] = set()
            for r in results:
                cid = r.get("chunk_id")
                if cid and str(cid) in chunks_by_id:
                    continue
                meta = r.get("metadata") or {}
                doc_id = meta.get("document_id")
                chunk_index = meta.get("chunk_index")
                if doc_id is None or chunk_index is None:
                    continue
                try:
                    doc_uuid = UUID(str(doc_id))
                    chunk_idx = int(chunk_index)
                except (TypeError, ValueError, AttributeError):
                    continue
                missing_pairs.add((doc_uuid, chunk_idx))

            chunks_by_pair: dict[tuple[str, int], DocumentChunk] = {}
            if missing_pairs:
                q = db.query(DocumentChunk).filter(
                    tuple_(DocumentChunk.document_id, DocumentChunk.chunk_index).in_(list(missing_pairs))
                )
                if tenant_filter:
                    q = q.filter(DocumentChunk.tenant_id == tenant_filter)
                for ck in q.all():
                    chunks_by_pair[(str(ck.document_id), int(ck.chunk_index))] = ck

            # Document-level user metadata is stored on documents.metadata.user (not per-chunk).
            # Fetch it once per document to enable metadata filtering like `document_user.tags`.
            doc_user_by_id: dict[str, dict[str, Any]] = {}
            doc_dataset_by_id: dict[str, str] = {}
            doc_ready_by_id: dict[str, bool] = {}
            doc_active_pipeline_key_by_id: dict[str, str] = {}
            doc_parse_quality_by_id: dict[str, float] = {}
            try:
                doc_ids: set[UUID] = set()
                for ck in list(chunks_by_id.values()) + list(chunks_by_pair.values()):
                    if ck and getattr(ck, "document_id", None):
                        doc_ids.add(UUID(str(ck.document_id)))
                if doc_ids:
                    dq = db.query(
                        DBDocument.id,
                        DBDocument.dataset_id,
                        DBDocument.status,
                        DBDocument.doc_metadata,
                        DBDocument.archived_at,
                        DBDocument.disabled_at,
                        DBDocument.publication_status,
                    ).filter(DBDocument.id.in_(sorted(doc_ids)))
                    if tenant_filter:
                        dq = dq.filter(DBDocument.tenant_id == tenant_filter)
                    for doc_id, ds_id, status, doc_meta, archived_at, disabled_at, publication_status in dq.all():
                        meta0 = doc_meta if isinstance(doc_meta, dict) else {}
                        user0 = meta0.get("user") if isinstance(meta0.get("user"), dict) else {}
                        if user0:
                            doc_user_by_id[str(doc_id)] = dict(user0)
                        pq_obj = meta0.get("parse_quality")
                        pq_score_raw = None
                        if isinstance(pq_obj, dict):
                            pq_score_raw = pq_obj.get("score")
                        elif pq_obj is not None:
                            pq_score_raw = pq_obj
                        try:
                            if pq_score_raw is not None:
                                pq_score = float(pq_score_raw)
                                if pq_score < 0.0:
                                    pq_score = 0.0
                                if pq_score > 1.0:
                                    pq_score = 1.0
                                doc_parse_quality_by_id[str(doc_id)] = float(pq_score)
                        except Exception as exc:
                            logger.debug("Ignoring non-critical retriever fallback failure: %s", exc)
                        if ds_id is not None:
                            doc_dataset_by_id[str(doc_id)] = str(ds_id)

                        # Versioning: compute active pipeline key for candidate-level trimming.
                        ready = (
                            bool(meta0.get("active_pipeline_ready"))
                            if "active_pipeline_ready" in meta0
                            else (str(status or "").lower() == "completed")
                        )
                        if archived_at is not None or disabled_at is not None:
                            ready = False
                        if str(publication_status or "published").strip().lower() != "published":
                            ready = False
                        doc_ready_by_id[str(doc_id)] = bool(ready)

                        active_key = str(meta0.get("active_doc_pipeline_key") or "").strip()
                        if not active_key:
                            active_hash = str(meta0.get("active_pipeline_hash") or meta0.get("pipeline_hash") or "").strip()
                            if active_hash:
                                active_key = f"{doc_id}:{active_hash}"
                        if ready and active_key:
                            doc_active_pipeline_key_by_id[str(doc_id)] = active_key
            except Exception as exc:
                _log_retriever_fallback('_enrich_results_with_db_metadata', exc)
                doc_user_by_id = {}
                doc_dataset_by_id = {}
                doc_ready_by_id = {}
                doc_active_pipeline_key_by_id = {}
                doc_parse_quality_by_id = {}

            # Candidate-level ACL trimming (security trimming) and dataset scoping.
            # This enables "open scope" retrieval (no precomputed allowed_doc_ids list) without leaking data.
            allowed_docs_str: set[str] | None = None
            if tenant_filter and account_id:
                try:
                    from app.services.document_access import get_allowed_document_id_sets

                    candidate_doc_ids: set[UUID] = set()
                    for k in doc_ready_by_id.keys():
                        if not k:
                            continue
                        try:
                            candidate_doc_ids.add(UUID(str(k)))
                        except Exception as exc:
                            _log_retriever_fallback('_enrich_results_with_db_metadata', exc)
                            continue
                    # Reduce work: if we cannot prove a doc is "ready", treat it as non-searchable.
                    ready_doc_ids: set[UUID] = set()
                    for doc_id, ok in doc_ready_by_id.items():
                        if not ok:
                            continue
                        try:
                            ready_doc_ids.add(UUID(str(doc_id)))
                        except Exception as exc:
                            _log_retriever_fallback('_enrich_results_with_db_metadata', exc)
                            continue
                    candidate_doc_ids = candidate_doc_ids & ready_doc_ids if ready_doc_ids else candidate_doc_ids

                    if dataset_filter is not None and doc_dataset_by_id:
                        want = str(dataset_filter)
                        candidate_doc_ids = {
                            did for did in candidate_doc_ids if str(did) in doc_dataset_by_id and doc_dataset_by_id[str(did)] == want
                        }

                    if candidate_doc_ids:
                        allowed_ids, _missing = get_allowed_document_id_sets(
                            db,
                            tenant_filter,
                            account_id,
                            list(candidate_doc_ids),
                            check_member=True,
                        )
                        allowed_docs_str = {str(did) for did in allowed_ids}
                    else:
                        allowed_docs_str = set()
                except Exception as exc:
                    _log_retriever_fallback('_enrich_results_with_db_metadata', exc)
                    # Fail closed: if ACL check fails, do not return potentially sensitive chunks.
                    allowed_docs_str = set()
            elif account_id and not tenant_filter:
                # If caller provided account_id but not tenant_id, fail closed.
                allowed_docs_str = set()

            resolved: list[dict[str, Any]] = []
            for r in results:
                meta = dict(r.get("metadata") or {})
                cid = r.get("chunk_id") or meta.get("chunk_id")
                ck = chunks_by_id.get(str(cid)) if cid else None

                if ck is None:
                    doc_id = meta.get("document_id")
                    chunk_index = meta.get("chunk_index")
                    try:
                        doc_uuid = UUID(str(doc_id))
                        chunk_idx = int(chunk_index)
                    except (TypeError, ValueError, AttributeError):
                        doc_uuid = None
                        chunk_idx = None
                    if doc_uuid is not None and chunk_idx is not None:
                        ck = chunks_by_pair.get((str(doc_uuid), chunk_idx))

                # If we know tenant_id, treat unresolved results as stale (e.g. orphan vectors).
                if ck is None and tenant_filter:
                    if stats0 is not None:
                        stats0["filtered_orphaned"] = int(stats0.get("filtered_orphaned", 0) or 0) + 1
                    continue

                if ck is not None:
                    # Enforce candidate-level dataset/ACL trimming once we know the resolved document_id.
                    doc_id_str = str(ck.document_id)
                    if allowed_docs_str is not None and doc_id_str not in allowed_docs_str:
                        if stats0 is not None:
                            stats0["filtered_acl"] = int(stats0.get("filtered_acl", 0) or 0) + 1
                        continue
                    if dataset_filter is not None:
                        want = str(dataset_filter)
                        if doc_dataset_by_id.get(doc_id_str) != want:
                            if stats0 is not None:
                                stats0["filtered_dataset"] = int(stats0.get("filtered_dataset", 0) or 0) + 1
                            continue
                    if getattr(ck, "disabled_at", None) is not None:
                        if stats0 is not None:
                            stats0["filtered_not_ready"] = int(stats0.get("filtered_not_ready", 0) or 0) + 1
                        continue
                    if doc_ready_by_id and not doc_ready_by_id.get(doc_id_str, False):
                        if stats0 is not None:
                            stats0["filtered_not_ready"] = int(stats0.get("filtered_not_ready", 0) or 0) + 1
                        continue

                    cid_str = str(ck.id)
                    r["chunk_id"] = cid_str
                    meta["chunk_id"] = cid_str
                    chunks_by_id[cid_str] = ck

                    # Use DB content as the source of truth for downstream citations/highlighting.
                    # Vector backends may store transformed text (e.g., embedding-only prefixes).
                    try:
                        db_content = ck.content or ""
                        if isinstance(db_content, str) and db_content and r.get("content") != db_content:
                            r["content"] = db_content
                    except Exception as exc:
                        logger.debug("Ignoring non-critical retriever fallback failure: %s", exc)

                    # Merge DB metadata (only fill empty fields, avoid overwriting vector-side score etc.)
                    stored_meta = dict(ck.doc_metadata or {})
                    # Fill in missing fields from persisted chunk metadata (rich JSONB).
                    for k, v in stored_meta.items():
                        if k not in meta or meta.get(k) in (None, "", [], {}):
                            meta[k] = v
                    if stored_meta.get("embedding_space_hash") and not meta.get("embedding_space_hash"):
                        meta["embedding_space_hash"] = stored_meta.get("embedding_space_hash")
                    if stored_meta.get("img_id") and not meta.get("img_id"):
                        meta["img_id"] = stored_meta.get("img_id")
                    if stored_meta.get("source") and not meta.get("source"):
                        meta["source"] = stored_meta.get("source")
                    if (ck.page_number is not None) and not meta.get("page"):
                        meta["page"] = ck.page_number
                    if (ck.page_number is not None) and not meta.get("page_number"):
                        meta["page_number"] = ck.page_number
                    # Position data enables precise UI highlighting / deep-linking.
                    if (ck.start_char is not None) and meta.get("start_char") is None:
                        meta["start_char"] = int(ck.start_char)
                    if (ck.end_char is not None) and meta.get("end_char") is None:
                        meta["end_char"] = int(ck.end_char)
                    if meta.get("chunk_index") is None:
                        try:
                            meta["chunk_index"] = int(getattr(ck, "chunk_index", None))
                        except Exception as exc:
                            logger.debug("Ignoring non-critical retriever fallback failure: %s", exc)
                    if stored_meta.get("parser_backend") and not meta.get("parser_backend"):
                        meta["parser_backend"] = stored_meta.get("parser_backend")
                    if stored_meta.get("doc_type_kwd") and not meta.get("doc_type_kwd"):
                        meta["doc_type_kwd"] = stored_meta.get("doc_type_kwd")
                    for key in (
                        "header_path",
                        "header_context",
                        "chunk_strategy",
                        "chunk_role",
                        "parent_id",
                        "hierarchy_basis",
                        "hierarchy_level",
                        "hierarchy_node_key",
                        "hierarchy_family_key",
                        "hierarchy_parent_key",
                        "hierarchy_sibling_index",
                        "hierarchy_prev_sibling_key",
                        "hierarchy_next_sibling_key",
                    ):
                        if stored_meta.get(key) and not meta.get(key):
                            meta[key] = stored_meta.get(key)

                    # Attach document-level user metadata for metadata filtering / enterprise search facets.
                    doc_user = doc_user_by_id.get(str(ck.document_id))
                    if doc_user and not meta.get("document_user"):
                        meta["document_user"] = doc_user
                    if meta.get("doc_parse_quality_score") is None:
                        pq_score = doc_parse_quality_by_id.get(str(ck.document_id))
                        if pq_score is not None:
                            meta["doc_parse_quality_score"] = float(pq_score)

                    # Embedding space guard (vector only): avoid mixing vectors created with different
                    # embedding models/providers/endpoints.
                    #
                    # Notes:
                    # - We only enforce this when the hit came from vector search (Milvus attaches
                    #   `metadata.score`), because BM25 is embedding-space agnostic.
                    # - Missing embedding_space_hash is treated as "unknown" (backward compatible).
                    if meta.get("score") is not None:
                        ck_space = str(meta.get("embedding_space_hash") or "").strip()
                        if ck_space and ck_space != embedding_space:
                            if stats0 is not None:
                                stats0["filtered_embedding_space"] = (
                                    int(stats0.get("filtered_embedding_space", 0) or 0) + 1
                                )
                            continue

                    # Candidate-level active pipeline trimming (avoid mixing versions when open-scoped).
                    active_key = doc_active_pipeline_key_by_id.get(doc_id_str)
                    if active_key:
                        ck_key = str(meta.get("doc_pipeline_key") or "").strip()
                        if not ck_key:
                            # Best-effort fallback from pipeline_hash.
                            ph = str(meta.get("pipeline_hash") or stored_meta.get("pipeline_hash") or "").strip()
                            if ph:
                                ck_key = f"{ck.document_id}:{ph}"
                        if not ck_key or ck_key != active_key:
                            if stats0 is not None:
                                stats0["filtered_pipeline_version"] = (
                                    int(stats0.get("filtered_pipeline_version", 0) or 0) + 1
                                )
                            continue

                r["metadata"] = meta
                resolved.append(r)

            # Apply the full metadata filter *after* DB enrichment.
            effective_metadata_filter = metadata_filter_override if metadata_filter_override is not None else self.metadata_filter
            if effective_metadata_filter and self.metadata_filter_enabled:
                try:
                    before = len(resolved)
                    from app.rag.core.filters import apply_metadata_filter_with_stats  # noqa: WPS433

                    resolved, mf_stats = apply_metadata_filter_with_stats(resolved, effective_metadata_filter)
                    blocked = int(mf_stats.get("blocked") or max(0, before - len(resolved)))
                    matched = int(mf_stats.get("matched") or len(resolved))
                    summary = mf_stats.get("summary") if isinstance(mf_stats.get("summary"), dict) else None
                    if stats0 is not None:
                        stats0["filtered_metadata_filter"] = int(blocked)
                        stats0["metadata_filter_blocked"] = int(blocked)
                        stats0["metadata_filter_matched"] = int(matched)
                        if summary:
                            stats0["metadata_filter"] = summary
                except Exception as exc:
                    logger.debug("Ignoring non-critical retriever fallback failure: %s", exc)

            if stats0 is not None:
                stats0["output_results"] = len(resolved)
            return resolved
        except Exception as exc:
            _log_retriever_fallback('_enrich_results_with_db_metadata', exc)
            if stats0 is not None:
                stats0["exception"] = str(exc)[:200]
            return results
        finally:
            try:
                db.close()
            except Exception as exc:
                logger.debug("Ignoring non-critical retriever fallback failure: %s", exc)

    def _expand_results_with_neighbors(self, results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Optionally attach adjacent chunks around top hits for better continuity."""
        if not results:
            return results

        window = max(0, int(getattr(settings, "RAG_CONTEXT_NEIGHBOR_WINDOW", 0) or 0))
        sibling_enabled = bool(getattr(settings, "RAG_CONTEXT_SIBLING_EXPAND_ENABLED", False))
        short_doc_max_chunks = max(0, int(getattr(settings, "RAG_CONTEXT_SIBLING_SHORT_DOC_MAX_CHUNKS", 0) or 0))
        if window <= 0 and not (sibling_enabled and short_doc_max_chunks > 0):
            return results

        max_added = max(0, int(getattr(settings, "RAG_CONTEXT_NEIGHBOR_MAX_ADDED", 0) or 0))
        sibling_max_added = max(
            0,
            int(getattr(settings, "RAG_CONTEXT_SIBLING_MAX_ADDED", max_added or 0) or (max_added or 0)),
        )
        tenant_filter = self.tenant_id

        # Version-aware neighbor fetch:
        # - Some installations keep multiple pipeline versions in `document_chunks`.
        # - We must avoid pulling neighbors from an inactive pipeline version, even for the same document.
        desired_pipeline_by_doc: dict[str, str] = {}

        anchors: list[tuple[dict[str, Any], UUID | None, int | None, str | None]] = []
        for r in results:
            meta = r.get("metadata") or {}
            doc_id = meta.get("document_id")
            chunk_index = meta.get("chunk_index")
            try:
                doc_uuid = UUID(str(doc_id)) if doc_id is not None else None
                idx = int(chunk_index) if chunk_index is not None else None
            except (TypeError, ValueError, AttributeError):
                doc_uuid = None
                idx = None
            pipeline_key = str(meta.get("doc_pipeline_key") or "").strip()
            if not pipeline_key and doc_uuid is not None:
                ph = str(meta.get("pipeline_hash") or "").strip()
                if ph:
                    pipeline_key = f"{doc_uuid}:{ph}"
            pipeline_key = pipeline_key or None
            if doc_uuid is not None and pipeline_key:
                desired_pipeline_by_doc.setdefault(str(doc_uuid), pipeline_key)
            anchors.append((r, doc_uuid, idx, pipeline_key))

        document_chunks_by_doc: dict[str, list[DocumentChunk]] = {}
        short_doc_ids: set[str] = set()
        doc_ids_for_sibling = {doc_uuid for _, doc_uuid, _, _ in anchors if doc_uuid is not None}

        needed_pairs: set[tuple[UUID, int]] = set()
        for _, doc_uuid, idx, _pk in anchors:
            if doc_uuid is not None and str(doc_uuid) in short_doc_ids:
                continue
            if doc_uuid is None or idx is None:
                continue
            for delta in range(-window, window + 1):
                if delta == 0:
                    continue
                neighbor_idx = idx + delta
                if neighbor_idx < 0:
                    continue
                needed_pairs.add((doc_uuid, neighbor_idx))

        if not needed_pairs:
            return results

        neighbors_by_pair: dict[tuple[str, int], DocumentChunk] = {}
        db = SessionLocal()
        try:
            if sibling_enabled and short_doc_max_chunks > 0 and doc_ids_for_sibling:
                q_all = db.query(DocumentChunk).filter(DocumentChunk.document_id.in_(list(doc_ids_for_sibling)))
                if tenant_filter:
                    q_all = q_all.filter(DocumentChunk.tenant_id == tenant_filter)
                for ck in q_all.all():
                    doc_key = str(ck.document_id)
                    desired = desired_pipeline_by_doc.get(doc_key)
                    if desired:
                        stored_meta = dict(getattr(ck, "doc_metadata", None) or {})
                        ck_key = str(stored_meta.get("doc_pipeline_key") or "").strip()
                        if not ck_key:
                            ph = str(stored_meta.get("pipeline_hash") or "").strip()
                            if ph:
                                ck_key = f"{ck.document_id}:{ph}"
                        if not ck_key or ck_key != desired:
                            continue
                    document_chunks_by_doc.setdefault(doc_key, []).append(ck)
                short_doc_ids = {
                    doc_key
                    for doc_key, rows in document_chunks_by_doc.items()
                    if select_document_expansion_mode(
                        total_chunks=len(rows),
                        short_doc_max_chunks=short_doc_max_chunks,
                    )
                    == "sibling"
                }

            q = db.query(DocumentChunk).filter(
                tuple_(DocumentChunk.document_id, DocumentChunk.chunk_index).in_(list(needed_pairs))
            )
            if tenant_filter:
                q = q.filter(DocumentChunk.tenant_id == tenant_filter)
            for ck in q.all():
                doc_key = str(ck.document_id)
                desired = desired_pipeline_by_doc.get(doc_key)
                if desired:
                    stored_meta = dict(getattr(ck, "doc_metadata", None) or {})
                    ck_key = str(stored_meta.get("doc_pipeline_key") or "").strip()
                    if not ck_key:
                        ph = str(stored_meta.get("pipeline_hash") or "").strip()
                        if ph:
                            ck_key = f"{ck.document_id}:{ph}"
                    if not ck_key or ck_key != desired:
                        continue
                neighbors_by_pair[(doc_key, int(ck.chunk_index))] = ck
        except Exception as exc:
            _log_retriever_fallback('_expand_results_with_neighbors', exc)
            return results
        finally:
            try:
                db.close()
            except Exception as exc:
                logger.debug("Ignoring non-critical retriever fallback failure: %s", exc)

        original_results_by_chunk_id: dict[str, dict[str, Any]] = {}
        for r in results:
            cid = r.get("chunk_id") or (r.get("metadata") or {}).get("chunk_id")
            if cid:
                original_results_by_chunk_id[str(cid)] = r
        expanded, _meta = expand_ranked_chunk_results(
            results=results,
            window=window,
            max_added=max_added,
            sibling_max_added=sibling_max_added,
            document_chunks_by_doc=document_chunks_by_doc,
            short_doc_ids=short_doc_ids,
            neighbors_by_pair=neighbors_by_pair,
            original_results_by_chunk_id=original_results_by_chunk_id,
        )
        return expanded

    def _stitch_results_for_continuity(self, results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        Reorder results to improve continuity by stitching contiguous chunk ranges.

        This is order-only: it never drops or adds results.

        Why:
        - Retrieval pipelines often return chunks in score order, which can interleave documents
          and fragment contiguous passages.
        - For prompt context (and UI previews), grouping contiguous chunks improves readability
          and reduces "jumping around" in the source material.
        """
        if not results:
            return results
        if not bool(getattr(settings, "RAG_CONTEXT_STITCHING_ENABLED", False)):
            return results

        def _score(r: dict[str, Any]) -> float:
            try:
                return float(r.get("score") or 0.0)
            except (TypeError, ValueError, AttributeError):
                return 0.0

        stitchable_by_doc: dict[str, list[tuple[int, int, dict[str, Any]]]] = {}
        singleton_groups: list[tuple[float, int, list[dict[str, Any]]]] = []

        for pos, r in enumerate(results):
            meta = r.get("metadata") or {}
            doc_id = meta.get("document_id")
            chunk_index = meta.get("chunk_index")
            doc_key = str(doc_id).strip() if doc_id is not None else ""
            try:
                idx = int(chunk_index) if chunk_index is not None else None
            except (TypeError, ValueError, AttributeError):
                idx = None
            if doc_key and idx is not None and idx >= 0:
                stitchable_by_doc.setdefault(doc_key, []).append((idx, pos, r))
            else:
                singleton_groups.append((_score(r), pos, [r]))

        groups: list[tuple[float, str, int, int, int, list[dict[str, Any]]]] = []
        # group tuple: (score, doc_id, start_idx, end_idx, min_pos, items)
        for doc_id, entries in stitchable_by_doc.items():
            entries.sort(key=lambda t: (t[0], t[1]))
            run: list[tuple[int, int, dict[str, Any]]] = []
            for idx, pos, r in entries:
                if not run:
                    run = [(idx, pos, r)]
                    continue
                if idx == run[-1][0] + 1:
                    run.append((idx, pos, r))
                    continue
                run_score = max(_score(x[2]) for x in run)
                start_idx = int(run[0][0])
                end_idx = int(run[-1][0])
                min_pos = min(int(x[1]) for x in run)
                groups.append((run_score, doc_id, start_idx, end_idx, min_pos, [x[2] for x in run]))
                run = [(idx, pos, r)]

            if run:
                run_score = max(_score(x[2]) for x in run)
                start_idx = int(run[0][0])
                end_idx = int(run[-1][0])
                min_pos = min(int(x[1]) for x in run)
                groups.append((run_score, doc_id, start_idx, end_idx, min_pos, [x[2] for x in run]))

        # Add singleton groups (no document_id/chunk_index); keep them sortable by score with stable tie-breakers.
        for score, pos, items in singleton_groups:
            groups.append((float(score), "", -1, -1, int(pos), items))

        # Sort stitched groups by their max relevance score, then deterministic tie-breakers.
        groups.sort(key=lambda g: (-float(g[0]), str(g[1]), int(g[2]), int(g[4])))

        stitched: list[dict[str, Any]] = []
        for _score_g, _doc_id, _start, _end, _pos, items in groups:
            stitched.extend(items)

        return stitched

    def _auto_merge_parent_child(self, results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        Parent-child auto merge (LlamaIndex AutoMergingRetriever-style, simplified).

        - When results contain many child hits for the same parent_id, collapse them into the parent chunk.
        - Two modes:
          - replace: drop children (and their neighbors) and insert/bump the parent once.
          - append: keep children and insert the parent once (deduped).
        """
        if not results:
            return results
        if not bool(getattr(settings, "RAG_PARENT_CHILD_AUTO_MERGE_ENABLED", False)):
            return results

        mode = str(getattr(settings, "RAG_PARENT_CHILD_AUTO_MERGE_MODE", "replace") or "replace").strip().lower()
        if mode not in {"replace", "append"}:
            mode = "replace"

        min_children = max(1, int(getattr(settings, "RAG_PARENT_CHILD_AUTO_MERGE_MIN_CHILDREN", 2) or 2))
        max_parents = max(0, int(getattr(settings, "RAG_PARENT_CHILD_AUTO_MERGE_MAX_PARENTS", 20) or 20))

        tenant_filter = self.tenant_id

        # Group child hits by (document_id, family collapse key).
        child_groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
        parent_results: dict[tuple[str, str], dict[str, Any]] = {}

        # For neighbor cleanup (replace mode).
        child_chunk_ids_by_group: dict[tuple[str, str], set[str]] = {}

        for r in results:
            meta = r.get("metadata") or {}
            role = str(meta.get("chunk_role") or "").strip().lower()
            doc_id = str(meta.get("document_id") or "").strip()
            family_key = self._resolve_family_collapse_key(meta, result=r)
            if not family_key or not doc_id:
                continue

            cid = r.get("chunk_id") or meta.get("chunk_id")
            cid_str = str(cid) if cid else ""

            if role == "parent":
                parent_results[(doc_id, family_key)] = r
            elif role == "child":
                key = (doc_id, family_key)
                child_groups.setdefault(key, []).append(r)
                if cid_str:
                    child_chunk_ids_by_group.setdefault(key, set()).add(cid_str)

        if not child_groups:
            return results

        # Version-aware parent materialization: only pull parent chunks from the same active pipeline
        # version as the retrieved children.
        desired_pipeline_by_doc: dict[str, str] = {}
        for r in results:
            meta = r.get("metadata") or {}
            doc_id = str(meta.get("document_id") or "").strip()
            if not doc_id:
                continue
            pipeline_key = str(meta.get("doc_pipeline_key") or "").strip()
            if not pipeline_key:
                ph = str(meta.get("pipeline_hash") or "").strip()
                if ph:
                    pipeline_key = f"{doc_id}:{ph}"
            if pipeline_key:
                desired_pipeline_by_doc.setdefault(doc_id, pipeline_key)

        # Select top groups (by best child score) to avoid excessive DB queries.
        scored_groups: list[tuple[float, tuple[str, str]]] = []
        for key, items in child_groups.items():
            best = 0.0
            for it in items:
                try:
                    best = max(best, float(it.get("score", 0.0) or 0.0))
                except (TypeError, ValueError, AttributeError):
                    continue
            scored_groups.append((best, key))
        scored_groups.sort(key=lambda x: x[0], reverse=True)
        if max_parents and len(scored_groups) > max_parents:
            scored_groups = scored_groups[:max_parents]

        # Decide which groups to materialize a parent for.
        selected_keys: list[tuple[str, str]] = []
        for _, key in scored_groups:
            if mode == "replace" and len(child_groups.get(key) or []) < min_children:
                continue
            selected_keys.append(key)

        if not selected_keys:
            return results

        # Fetch parent chunks not already present in results.
        missing_keys = [k for k in selected_keys if k not in parent_results]
        fetched_parents: dict[tuple[str, str], DocumentChunk] = {}

        if missing_keys:
            doc_ids: set[UUID] = set()
            family_keys: set[str] = set()
            for doc_id, family_key in missing_keys:
                try:
                    doc_ids.add(UUID(doc_id))
                except Exception as exc:
                    _log_retriever_fallback('_auto_merge_parent_child', exc)
                    continue
                if family_key:
                    family_keys.add(family_key)

            if doc_ids and family_keys:
                db = SessionLocal()
                try:
                    q = db.query(DocumentChunk).filter(DocumentChunk.document_id.in_(list(doc_ids)))
                    if tenant_filter:
                        q = q.filter(DocumentChunk.tenant_id == tenant_filter)
                    # Prefer hierarchy_family_key and keep parent_id as a backward-compatible fallback.
                    q = q.filter(DocumentChunk.doc_metadata["chunk_role"].astext == "parent")  # type: ignore[attr-defined]
                    q = q.filter(
                        or_(
                            DocumentChunk.doc_metadata["hierarchy_family_key"].astext.in_(list(family_keys)),  # type: ignore[attr-defined]
                            DocumentChunk.doc_metadata["parent_id"].astext.in_(list(family_keys)),  # type: ignore[attr-defined]
                        )
                    )
                    for ck in q.all():
                        meta = dict(getattr(ck, "doc_metadata", None) or {})
                        family_key = self._resolve_family_collapse_key(meta)
                        if not family_key:
                            continue
                        desired = desired_pipeline_by_doc.get(str(ck.document_id))
                        if desired:
                            ck_key = str(meta.get("doc_pipeline_key") or "").strip()
                            if not ck_key:
                                ph = str(meta.get("pipeline_hash") or "").strip()
                                if ph:
                                    ck_key = f"{ck.document_id}:{ph}"
                            if not ck_key or ck_key != desired:
                                continue
                        fetched_parents[(str(ck.document_id), family_key)] = ck
                except Exception as exc:
                    _log_retriever_fallback('_auto_merge_parent_child', exc)
                    fetched_parents = {}
                finally:
                    try:
                        db.close()
                    except Exception as exc:
                        logger.debug("Ignoring non-critical retriever fallback failure: %s", exc)

        # Helper: materialize a parent result dict.
        def _parent_result_for(key: tuple[str, str], *, best_child_score: float) -> dict[str, Any] | None:
            if key in parent_results:
                # If parent is already present (e.g., neighbor expansion), bump its score and mark role.
                existing = parent_results[key]
                meta = dict(existing.get("metadata") or {})
                meta["retrieval_role"] = "parent"
                existing["metadata"] = meta
                try:
                    existing_score = float(existing.get("score", 0.0) or 0.0)
                except (TypeError, ValueError, AttributeError):
                    existing_score = 0.0
                existing["score"] = max(existing_score, best_child_score * 0.97)
                return existing

            ck = fetched_parents.get(key)
            if ck is None:
                return None

            cid = str(ck.id)
            stored_meta = dict(ck.doc_metadata or {})
            stored_meta.setdefault("tenant_id", str(ck.tenant_id))
            stored_meta.setdefault("document_id", str(ck.document_id))
            stored_meta.setdefault("chunk_index", int(ck.chunk_index))
            stored_meta.setdefault("chunk_id", cid)
            if ck.page_number is not None:
                stored_meta.setdefault("page", ck.page_number)
            if not stored_meta.get("source"):
                stored_meta["source"] = "unknown"
            stored_meta["retrieval_role"] = "parent"

            return {
                "chunk_id": cid,
                "content": ck.content,
                "metadata": stored_meta,
                "score": float(best_child_score * 0.97),
            }

        # Build quick access for best child score per group.
        best_score_by_group: dict[tuple[str, str], float] = {}
        for key in selected_keys:
            best = 0.0
            for it in child_groups.get(key) or []:
                try:
                    best = max(best, float(it.get("score", 0.0) or 0.0))
                except (TypeError, ValueError, AttributeError):
                    continue
            best_score_by_group[key] = best

        if mode == "append":
            inserted: set[tuple[str, str]] = set()
            out: list[dict[str, Any]] = []
            for r in results:
                out.append(r)
                meta = r.get("metadata") or {}
                role = str(meta.get("chunk_role") or "").strip().lower()
                if role != "child":
                    continue
                key = (
                    str(meta.get("document_id") or "").strip(),
                    self._resolve_family_collapse_key(meta, result=r),
                )
                if key not in selected_keys or key in inserted:
                    continue
                # Parent already present in results (e.g., neighbor expansion) -> don't duplicate.
                if key in parent_results:
                    inserted.add(key)
                    continue
                # Only insert if we can materialize the parent.
                parent = _parent_result_for(key, best_child_score=best_score_by_group.get(key, 0.0))
                if parent is not None:
                    out.append(parent)
                    inserted.add(key)
            return out

        # replace mode: collapse groups.
        to_replace = set(selected_keys)
        removed_child_ids: set[str] = set()
        for key in to_replace:
            removed_child_ids |= child_chunk_ids_by_group.get(key, set())

        inserted: set[tuple[str, str]] = set()
        out: list[dict[str, Any]] = []
        for r in results:
            meta = r.get("metadata") or {}
            cid = r.get("chunk_id") or meta.get("chunk_id")
            cid_str = str(cid) if cid else ""

            # Drop neighbors that were added for removed children.
            if meta.get("retrieval_role") == "neighbor":
                if str(meta.get("neighbor_of") or "") in removed_child_ids:
                    continue

            role = str(meta.get("chunk_role") or "").strip().lower()
            key = (
                str(meta.get("document_id") or "").strip(),
                self._resolve_family_collapse_key(meta, result=r),
            )

            if role == "child" and key in to_replace:
                if key in inserted:
                    continue
                parent = _parent_result_for(key, best_child_score=best_score_by_group.get(key, 0.0))
                if parent is not None:
                    out.append(parent)
                inserted.add(key)
                continue

            # If parent is already present, keep it (and mark as parent role).
            if role == "parent" and key in to_replace:
                pr = _parent_result_for(key, best_child_score=best_score_by_group.get(key, 0.0))
                if pr is not None:
                    # Ensure we only keep one parent per group.
                    if key in inserted:
                        continue
                    out.append(pr)
                    inserted.add(key)
                    continue

            # Keep other results as-is.
            if cid_str and cid_str in removed_child_ids and role == "child":
                continue
            out.append(r)

        return out

    def _get_relevant_documents(
        self,
        query: str,
        *,
        run_manager: CallbackManagerForRetrieverRun,
    ) -> list[Document]:
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
        if self.dataset_id is None and not (self.document_ids or []):
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
            if self.dataset_id is None and self.tenant_id and (self.account_id or "").strip():
                overfetch_enabled = True
                overfetch_reasons.append("open_scope_acl")
            if metadata_filter_requested:
                overfetch_enabled = True
                overfetch_reasons.append("metadata_filter")

        if overfetch_enabled:
            mult = max(1, int(getattr(settings, "RETRIEVAL_OVERFETCH_MULTIPLIER", 1) or 1))
            if mult > 1:
                search_k = max(search_k, requested_k * mult)
                cap = int(getattr(settings, "RETRIEVAL_OVERFETCH_MAX_K", 0) or 0)
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
            "overfetch_multiplier": int(getattr(settings, "RETRIEVAL_OVERFETCH_MULTIPLIER", 1) or 1),
            "overfetch_cap_k": int(getattr(settings, "RETRIEVAL_OVERFETCH_MAX_K", 0) or 0),
            "query_normalization": {
                "original": original_query,
                "normalized": query,
                "applied_rules": list(query_norm.applied_rules or []),
            },
            "scope": {
                "tenant_id": str(self.tenant_id or ""),
                "account_id_present": bool((self.account_id or "").strip()),
                "dataset_id": str(self.dataset_id or ""),
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

        results = self._hybrid_search(
            query=query,
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
            logger.debug("Ignoring non-critical retriever fallback failure: %s", exc)
        enrich1: dict[str, Any] = {}
        try:
            results = self._enrich_results_with_db_metadata(
                results,
                stats=enrich1,
                metadata_filter_override=effective_metadata_filter,
            )
        except TypeError as exc:
            if "metadata_filter_override" not in str(exc):
                raise
            results = self._enrich_results_with_db_metadata(results, stats=enrich1)
        debug["enrich_pass1"] = enrich1
        n_enrich1 = len(results or [])

        results = self._expand_results_with_neighbors(results)
        debug["neighbors_delta"] = len(results or []) - n_enrich1

        n_neighbors = len(results or [])
        results = self._auto_merge_parent_child(results)
        debug["parent_child_merge_delta"] = len(results or []) - n_neighbors
        # Neighbor expansion / parent-child merges can introduce additional chunks that were
        # not part of the original retrieval result set. Re-apply DB enrichment + ACL/version
        # trimming to guarantee defense-in-depth and avoid leaking stale/non-active pipelines.
        enrich2: dict[str, Any] = {}
        try:
            results = self._enrich_results_with_db_metadata(
                results,
                stats=enrich2,
                metadata_filter_override=effective_metadata_filter,
            )
        except TypeError as exc:
            if "metadata_filter_override" not in str(exc):
                raise
            results = self._enrich_results_with_db_metadata(results, stats=enrich2)
        debug["enrich_pass2"] = enrich2

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
        stitch_enabled = bool(getattr(settings, "RAG_CONTEXT_STITCHING_ENABLED", False))
        debug["stitching_enabled"] = stitch_enabled
        prefix = list(results[:requested_k]) if results else []
        if stitch_enabled and prefix:
            try:
                prefix = self._stitch_results_for_continuity(prefix)
            except Exception as exc:
                logger.debug("Ignoring non-critical retriever fallback failure: %s", exc)

        docs: list[Document] = []
        for r in prefix:
            meta = dict(r.get("metadata") or {})
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
        Apply optional lifecycle governance preferences at the *final candidate ranking* stage.

        This is disabled by default and must not change behavior unless explicitly enabled.

        Policies (opt-in):
        - prefer_authority: small additive boost based on documents.authority_level (0-100)
        - prefer_latest: small additive boost for recently updated documents
        - filter_superseded: drop documents that are superseded by another active-ready doc
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

        if not enabled:
            return results

        # Avoid surprises: only apply cross-document lifecycle policies when dataset scoped.
        # (When callers explicitly scope by document_ids, do not remove/reorder docs implicitly.)
        if self.dataset_id is None:
            if stats is not None:
                stats["skip_reason"] = "no_dataset_scope"
            return results

        tenant_id = self.tenant_id
        if tenant_id is None:
            if stats is not None:
                stats["skip_reason"] = "no_tenant_scope"
            return results

        doc_ids: set[str] = set()
        for r in results:
            did = self._get_doc_id(r)
            if did:
                doc_ids.add(did)
        if stats is not None:
            stats["input_results"] = len(results)

        if not doc_ids:
            if stats is not None:
                stats["skip_reason"] = "no_candidate_docs"
            return results

        doc_uuid_list: list[UUID] = []
        for did in doc_ids:
            try:
                doc_uuid_list.append(UUID(str(did)))
            except (TypeError, ValueError, AttributeError):
                continue
        if stats is not None:
            stats["candidate_docs"] = len(doc_uuid_list)
        if not doc_uuid_list:
            if stats is not None:
                stats["skip_reason"] = "invalid_doc_ids"
            return results

        # Query doc-level features in a single bounded DB roundtrip.
        # NOTE: Do not attach raw values to result metadata; keep observability in retriever_debug only.
        doc_features: dict[str, dict[str, Any]] = {}
        superseded_doc_ids: set[str] = set()

        db = SessionLocal()
        try:
            if prefer_authority or prefer_latest:
                rows = (
                    db.query(
                        DBDocument.id,
                        DBDocument.authority_level,
                        DBDocument.updated_at,
                        DBDocument.created_at,
                    )
                    .filter(
                        DBDocument.tenant_id == tenant_id,
                        DBDocument.dataset_id == self.dataset_id,
                        DBDocument.id.in_(sorted(doc_uuid_list)),
                    )
                    .all()
                )
                for did, auth, updated_at, created_at in rows:
                    ts = updated_at or created_at
                    try:
                        ts_sec = float(ts.timestamp()) if ts is not None else None
                    except Exception as exc:
                        _log_retriever_fallback('_apply_governance_policy', exc)
                        ts_sec = None
                    try:
                        auth_i = int(auth) if auth is not None else 0
                    except (TypeError, ValueError, AttributeError):
                        auth_i = 0
                    doc_features[str(did)] = {"authority_level": auth_i, "updated_ts": ts_sec}

            if filter_superseded:
                sup_rows = (
                    db.query(
                        DBDocument.supersedes_document_id,
                        DBDocument.status,
                        DBDocument.doc_metadata,
                        DBDocument.archived_at,
                        DBDocument.disabled_at,
                        DBDocument.publication_status,
                    )
                    .filter(
                        DBDocument.tenant_id == tenant_id,
                        DBDocument.dataset_id == self.dataset_id,
                        DBDocument.supersedes_document_id.isnot(None),
                        DBDocument.supersedes_document_id.in_(sorted(doc_uuid_list)),
                    )
                    .all()
                )
                for supersedes_id, status, meta, archived_at, disabled_at, publication_status in sup_rows:
                    if supersedes_id is None:
                        continue
                    # Only treat as superseded when the superseding doc is "active-ready".
                    # (If the newer doc is archived/disabled/processing, keep the older doc.)
                    ready = False
                    try:
                        meta0 = meta if isinstance(meta, dict) else {}
                        if "active_pipeline_ready" in meta0:
                            ready = bool(meta0.get("active_pipeline_ready"))
                        else:
                            ready = str(status or "").lower() == "completed"
                        if archived_at is not None or disabled_at is not None:
                            ready = False
                        if str(publication_status or "published").strip().lower() != "published":
                            ready = False
                    except (TypeError, ValueError, AttributeError):
                        ready = False
                    if not ready:
                        continue
                    superseded_doc_ids.add(str(supersedes_id))
        except Exception as exc:
            _log_retriever_fallback('_apply_governance_policy', exc)
            # Fail open: governance policy must never break retrieval.
            doc_features = {}
            superseded_doc_ids = set()
        finally:
            try:
                db.close()
            except Exception as exc:
                logger.debug("Ignoring non-critical retriever fallback failure: %s", exc)

        out = list(results)

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
        return self._get_relevant_documents(query, run_manager=CallbackManagerForRetrieverRun.get_noop_manager())

    def _result_key(self, result: dict[str, Any]) -> str:
        meta = result.get("metadata") or {}
        doc_id = meta.get("document_id")
        chunk_index = meta.get("chunk_index")
        if doc_id is not None and chunk_index is not None:
            return f"{doc_id}:{chunk_index}"
        cid = result.get("chunk_id") or meta.get("chunk_id")
        if cid:
            return str(cid)
        content = str(result.get("content") or "")
        return f"content:{stable_hash(content)}"

    def _resolve_family_collapse_key(self, meta: dict[str, Any], *, result: dict[str, Any] | None = None) -> str:
        for key in ("hierarchy_family_key", "parent_id", "parent_node_id"):
            value = str(meta.get(key) or "").strip()
            if value:
                return value

        role = str(meta.get("chunk_role") or "").strip().lower()
        if role == "parent":
            for key in ("hierarchy_node_key", "chunk_key"):
                value = str(meta.get(key) or "").strip()
                if value:
                    return value

        doc_id = meta.get("document_id")
        chunk_index = meta.get("chunk_index")
        if doc_id is not None and chunk_index is not None:
            return f"{doc_id}:{chunk_index}"

        if result is not None:
            chunk_id = result.get("chunk_id") or meta.get("chunk_id")
            if chunk_id:
                return str(chunk_id).strip()

        return ""

    def _should_apply_hierarchy_family_collapse(self) -> bool:
        if not bool(self.enable_hierarchy_recall):
            return False
        if not bool(self.hierarchy_family_collapse):
            return False
        return bool(is_recall_first_profile(self.retrieval_profile))

    def _collapse_results_by_family(
        self,
        results: list[dict[str, Any]],
        *,
        stats: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        if stats is not None:
            stats.clear()

        enabled = self._should_apply_hierarchy_family_collapse()
        if stats is not None:
            stats["enabled"] = bool(enabled)
            stats["retrieval_profile"] = str(self.retrieval_profile or "").strip().lower() or None
            stats["input_results"] = len(results or [])

        if not enabled or not results:
            if stats is not None:
                stats["output_results"] = len(results or [])
                stats["collapsed_results"] = 0
            return results

        out: list[dict[str, Any]] = []
        seen_keys: set[str] = set()
        collapsed = 0
        for r in results:
            meta = r.get("metadata") or {}
            family_key = self._resolve_family_collapse_key(meta, result=r)
            if family_key and family_key in seen_keys:
                collapsed += 1
                continue
            if family_key:
                seen_keys.add(family_key)
            out.append(r)

        if stats is not None:
            stats["output_results"] = len(out)
            stats["collapsed_results"] = int(collapsed)
            stats["distinct_families"] = len(seen_keys)

        return out

    def _get_doc_id(self, result: dict[str, Any]) -> str:
        meta = result.get("metadata") or {}
        doc_id = meta.get("document_id")
        return str(doc_id) if doc_id is not None else ""

    def _match_metadata_filter(self, meta: dict[str, Any], filter_spec: dict[str, Any]) -> bool:
        return match_metadata_filter(meta, filter_spec)

    @staticmethod
    def _tokenize_for_similarity(text: str) -> set[str]:
        raw = (text or "").strip()
        if not raw:
            return set()
        tokens: list[str] = []
        for token in jieba.cut_for_search(raw):
            tok = str(token).strip()
            if not tok:
                continue
            if tok.isascii():
                if len(tok) < 2:
                    continue
                tok = tok.casefold()
                if tok.isdigit():
                    continue
                if tok in STOPWORDS:
                    continue
            else:
                if len(tok) < 2:
                    continue
                if tok in STOPWORDS:
                    continue
            tokens.append(tok)
        return set(tokens)

    @staticmethod
    def _jaccard(a: set[str], b: set[str]) -> float:
        if not a or not b:
            return 0.0
        inter = a & b
        union = a | b
        return (len(inter) / len(union)) if union else 0.0

    @staticmethod
    def _fingerprint(text: str) -> str:
        norm = re.sub(r"\s+", " ", (text or "").strip())
        return norm.casefold()

    def _deduplicate_results(self, results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not results or not bool(self.dedup_enabled):
            return results

        threshold = float(self.dedup_jaccard_threshold or 0.0)
        threshold = max(0.0, min(threshold, 1.0))
        max_compare = int(self.dedup_max_compare or 0)
        max_compare = max(0, max_compare)

        near_enabled = bool(getattr(settings, "RETRIEVAL_NEAR_DEDUP_ENABLED", False))
        near_thr = max(0, int(getattr(settings, "RETRIEVAL_NEAR_DEDUP_HAMMING_THRESHOLD", 0) or 0))
        near_max_compare = max(0, int(getattr(settings, "RETRIEVAL_NEAR_DEDUP_MAX_COMPARE", 0) or 0))
        if near_enabled:
            try:
                from app.rag.preprocessing.simhash import hamming_distance64  # noqa: WPS433
            except (TypeError, ValueError, AttributeError):
                near_enabled = False

        seen_chunk_ids: set[str] = set()
        seen_content_hashes: set[str] = set()
        seen_fingerprints: set[str] = set()
        kept: list[dict[str, Any]] = []
        kept_tokens_by_doc: dict[str, list[set[str]]] = {}
        kept_simhashes: list[int] = []
        dropped_near = 0
        dropped_content_hash = 0

        for r in results:
            meta = r.get("metadata") or {}
            cid = r.get("chunk_id") or meta.get("chunk_id")
            if cid:
                scid = str(cid)
                if scid in seen_chunk_ids:
                    continue
                seen_chunk_ids.add(scid)

            content = (r.get("content") or "").strip()
            if not content:
                continue

            # Wave19-T068: content-based dedup across modalities.
            #
            # Prefer a stable ingestion-time content hash (when present) to avoid:
            # - modality duplication (e.g., OCR text vs extracted text),
            # - expensive tokenization work when exact duplicates exist.
            ch = meta.get("content_hash")
            if ch is not None:
                sch = str(ch).strip()
                if sch:
                    if sch in seen_content_hashes:
                        dropped_content_hash += 1
                        continue
                    seen_content_hashes.add(sch)

            fp = self._fingerprint(content)
            if fp in seen_fingerprints:
                continue
            seen_fingerprints.add(fp)

            if near_enabled:
                sh_hex = str(meta.get("simhash64") or "").strip().lower()
                if sh_hex:
                    try:
                        sh_int = int(sh_hex, 16) & ((1 << 64) - 1)
                    except (TypeError, ValueError, AttributeError):
                        sh_int = None
                    if sh_int is not None:
                        compare_simhashes = kept_simhashes
                        if near_max_compare and len(compare_simhashes) > near_max_compare:
                            compare_simhashes = compare_simhashes[-near_max_compare:]
                        is_dup = any(hamming_distance64(sh_int, prev) <= near_thr for prev in compare_simhashes)
                        if is_dup:
                            dropped_near += 1
                            continue

            doc_id = self._get_doc_id(r)
            if threshold > 0.0 and doc_id:
                tokens = self._tokenize_for_similarity(content)
                if tokens:
                    compare_sets = kept_tokens_by_doc.get(doc_id) or []
                    if max_compare and len(compare_sets) > max_compare:
                        compare_sets = compare_sets[-max_compare:]
                    is_dup = any(self._jaccard(tokens, prev) >= threshold for prev in compare_sets if prev)
                    if is_dup:
                        continue
                    kept_tokens_by_doc.setdefault(doc_id, []).append(tokens)

            kept.append(r)
            if near_enabled:
                sh_hex = str(meta.get("simhash64") or "").strip().lower()
                if sh_hex:
                    try:
                        kept_simhashes.append(int(sh_hex, 16) & ((1 << 64) - 1))
                    except Exception as exc:
                        logger.debug("Ignoring non-critical retriever fallback failure: %s", exc)

        # Best-effort: expose dedup controls/impact in retriever_debug.channels for diagnostics.
        # Important: emit near-dedup fields even when disabled to avoid "hidden filtering" ambiguity.
        try:
            if isinstance(self._last_channel_metrics, dict):
                dedup_meta = self._last_channel_metrics.get("dedup")
                if not isinstance(dedup_meta, dict):
                    dedup_meta = {}
                    self._last_channel_metrics["dedup"] = dedup_meta
                dedup_meta["near_dedup_enabled"] = bool(near_enabled)
                dedup_meta["near_dedup_dropped"] = int(dropped_near)
                dedup_meta["near_dedup_hamming_threshold"] = int(near_thr)
                dedup_meta["near_dedup_max_compare"] = int(near_max_compare)
                dedup_meta["content_hash_dropped"] = int(dropped_content_hash)
        except Exception as exc:
            logger.debug("Ignoring non-critical retriever fallback failure: %s", exc)

        return kept

    def _apply_document_diversity(
        self,
        results: list[dict[str, Any]],
        *,
        top_k: int,
        stats: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        max_per_doc = int(self.max_chunks_per_doc or 0)
        max_per_page = int(getattr(self, "max_chunks_per_page", 0) or 0)
        min_docs = int(self.min_distinct_docs or 0)

        def _page_key(r: dict[str, Any]) -> tuple[str, int] | None:
            meta = r.get("metadata") or {}
            doc_id = self._get_doc_id(r)
            if not doc_id:
                return None
            raw = meta.get("page_number")
            if raw is None:
                raw = meta.get("page")
            if raw is None:
                return None
            try:
                page = int(raw)
            except (TypeError, ValueError, AttributeError):
                return None
            return (doc_id, page)

        k_cap = max(0, int(top_k or 0))
        pre_top = (results or [])[:k_cap]
        pre_keys = {self._result_key(r) for r in pre_top}
        pre_docs = {did for did in (self._get_doc_id(r) for r in pre_top) if did}
        pre_pages = {pk for pk in (_page_key(r) for r in pre_top) if pk is not None}

        if stats is not None:
            stats.clear()
            stats.update(
                {
                    "max_chunks_per_doc": int(max_per_doc),
                    "max_chunks_per_page": int(max_per_page),
                    "min_distinct_docs": int(min_docs),
                    "pre_unique_docs": int(len(pre_docs)),
                    "pre_unique_pages": int(len(pre_pages)),
                }
            )

        if not results:
            if stats is not None:
                stats.update(
                    {
                        "post_unique_docs": 0,
                        "post_unique_pages": 0,
                        "moved_out": 0,
                        "moved_in": 0,
                    }
                )
            return results

        if max_per_doc <= 0 and max_per_page <= 0 and min_docs <= 0:
            if stats is not None:
                stats.update(
                    {
                        "post_unique_docs": int(len(pre_docs)),
                        "post_unique_pages": int(len(pre_pages)),
                        "moved_out": 0,
                        "moved_in": 0,
                    }
                )
            return results

        groups: dict[str, list[dict[str, Any]]] = {}
        for r in results:
            groups.setdefault(self._get_doc_id(r), []).append(r)

        must_have: list[dict[str, Any]] = []
        if min_docs > 0:
            firsts = [items[0] for items in groups.values() if items]
            firsts.sort(key=lambda x: float(x.get("score", 0.0) or 0.0), reverse=True)
            must_have = firsts[: max(0, min(min_docs, len(firsts), top_k))]

        selected: list[dict[str, Any]] = []
        used_keys: set[str] = set()
        per_doc = Counter()
        per_page = Counter()
        for r in must_have:
            k = self._result_key(r)
            if k in used_keys:
                continue
            used_keys.add(k)
            selected.append(r)
            doc_id = self._get_doc_id(r)
            per_doc[doc_id] += 1
            pk = _page_key(r)
            if pk is not None:
                per_page[pk] += 1

        overflow: list[dict[str, Any]] = []
        for r in results:
            if len(selected) >= top_k:
                break
            k = self._result_key(r)
            if k in used_keys:
                continue
            doc_id = self._get_doc_id(r)
            if max_per_doc > 0 and per_doc[doc_id] >= max_per_doc:
                overflow.append(r)
                continue
            pk = _page_key(r)
            if max_per_page > 0 and pk is not None and per_page[pk] >= max_per_page:
                overflow.append(r)
                continue
            used_keys.add(k)
            selected.append(r)
            per_doc[doc_id] += 1
            if pk is not None:
                per_page[pk] += 1

        if len(selected) < top_k and overflow:
            for r in overflow:
                if len(selected) >= top_k:
                    break
                k = self._result_key(r)
                if k in used_keys:
                    continue
                used_keys.add(k)
                selected.append(r)

        if len(selected) >= len(results):
            out_all = selected
        else:
            rest = [r for r in results if self._result_key(r) not in used_keys]
            out_all = selected + rest

        if stats is not None:
            post_top = out_all[:k_cap]
            post_keys = {self._result_key(r) for r in post_top}
            post_docs = {did for did in (self._get_doc_id(r) for r in post_top) if did}
            post_pages = {pk for pk in (_page_key(r) for r in post_top) if pk is not None}
            stats.update(
                {
                    "post_unique_docs": int(len(post_docs)),
                    "post_unique_pages": int(len(post_pages)),
                    "moved_out": int(len(pre_keys - post_keys)),
                    "moved_in": int(len(post_keys - pre_keys)),
                }
            )

        return out_all

    def _merge_results(
        self,
        vector_results: list[dict[str, Any]],
        bm25_results: list[dict[str, Any]],
        lexical_results: list[dict[str, Any]] | None = None,
        sparse_results: list[dict[str, Any]] | None = None,
        query: str | None = None,
        alpha: float = 0.5,
        fusion_strategy: str | None = None,
        rrf_k: int | None = None,
        top_k: int | None = None,
    ) -> list[dict[str, Any]]:
        """Merge retrieval channel results into a single ranked list."""

        lexical_results = list(lexical_results or [])
        sparse_results = list(sparse_results or [])

        field_aware_enabled = bool(getattr(settings, "RETRIEVAL_FIELD_AWARE_RECALL_ENABLED", False))
        field_aware_title_boost = max(0.0, float(getattr(settings, "RETRIEVAL_FIELD_AWARE_TITLE_BOOST", 0.08) or 0.0))
        field_aware_heading_boost = max(0.0, float(getattr(settings, "RETRIEVAL_FIELD_AWARE_HEADING_BOOST", 0.05) or 0.0))
        field_aware_max_boost = max(0.0, float(getattr(settings, "RETRIEVAL_FIELD_AWARE_MAX_BOOST", 0.10) or 0.0))
        field_aware_title_boost = min(field_aware_title_boost, field_aware_max_boost)
        field_aware_heading_boost = min(field_aware_heading_boost, field_aware_max_boost)
        chunk_type_weighting_enabled = bool(getattr(settings, "RETRIEVAL_CHUNK_TYPE_WEIGHTING_ENABLED", False))
        chunk_type_match_boost = max(0.0, float(getattr(settings, "RETRIEVAL_CHUNK_TYPE_MATCH_BOOST", 0.08) or 0.0))

        def _resolve_chunk_type(result: dict[str, Any]) -> str:
            meta = result.get("metadata") or {}
            raw = str(
                meta.get("chunk_type")
                or meta.get("content_type")
                or meta.get("visual_kind")
                or ""
            ).strip().lower()
            if raw in {"text", "formula", "table", "code", "figure", "chart_data", "seal"}:
                return raw
            if raw == "chart":
                return "figure"
            role = str(meta.get("chunk_semantic_role") or "").strip().lower()
            if role == "code":
                return "code"
            if role == "table":
                return "table"
            return "text"

        def _resolve_query_chunk_type_signal(text: str | None) -> str | None:
            raw = str(text or "").strip().lower()
            if not raw:
                return None
            if any(token in raw for token in ("表格", "字段", "列", "schema", "table", "column")):
                return "table"
            if any(token in raw for token in ("公式", "latex", "equation", "math", "公式识别")):
                return "formula"
            if any(token in raw for token in ("代码", "sql", "python", "bash", "json", "yaml", "脚本", "code")):
                return "code"
            if any(token in raw for token in ("图表", "曲线", "趋势图", "chart", "plot", "graph")):
                return "chart_data"
            if any(token in raw for token in ("公章", "印章", "seal", "stamp")):
                return "seal"
            return None

        preferred_chunk_type = _resolve_query_chunk_type_signal(query)

        def _chunk_type_boost(chunk_type: str) -> float:
            if not chunk_type_weighting_enabled or not preferred_chunk_type:
                return 0.0
            if chunk_type == preferred_chunk_type:
                return chunk_type_match_boost
            if preferred_chunk_type == "chart_data" and chunk_type == "figure":
                return max(0.0, chunk_type_match_boost * 0.75)
            return 0.0

        def _resolve_field_signal(result: dict[str, Any]) -> str:
            meta = result.get("metadata") or {}
            hinted = str(
                meta.get("embedding_field_role")
                or meta.get("embedding_field_kind")
                or meta.get("field_channel")
                or ""
            ).strip().lower()
            if hinted in {"title", "heading", "body"}:
                return hinted

            chunk_id = str(result.get("chunk_id") or meta.get("chunk_id") or "").strip().lower()
            if chunk_id.endswith(":title"):
                return "title"
            if chunk_id.endswith(":heading"):
                return "heading"
            return "body"

        def _field_boost(field_signal: str) -> float:
            if not field_aware_enabled:
                return 0.0
            if field_signal == "title":
                return field_aware_title_boost
            if field_signal == "heading":
                return field_aware_heading_boost
            return 0.0

        def normalize(results: list[dict[str, Any]], *, channel: str) -> dict[str, dict[str, Any]]:
            if not results:
                return {}
            scores = [r.get("score", 0.0) for r in results]
            min_score = min(scores)
            max_score = max(scores)
            rng = max_score - min_score if max_score > min_score else 1.0
            out: dict[str, dict[str, Any]] = {}
            for r in results:
                key = self._result_key(r)
                norm_score = (r.get("score", 0.0) - min_score) / rng
                field_signal = "body"
                field_boost = 0.0
                chunk_type = _resolve_chunk_type(r)
                chunk_type_boost = _chunk_type_boost(chunk_type)
                if channel == "vector":
                    field_signal = _resolve_field_signal(r)
                    field_boost = min(_field_boost(field_signal), field_aware_max_boost)
                scored = float(norm_score) + float(field_boost) + float(chunk_type_boost)
                existing = out.get(key)
                if existing is None or float(scored) > float(existing.get("score", 0.0) or 0.0):
                    out[key] = {
                        "score": float(scored),
                        "base_score": float(norm_score),
                        "data": r,
                        "chunk_type": chunk_type,
                        "chunk_type_boost": float(chunk_type_boost),
                        "field_aware_signal": field_signal if channel == "vector" else None,
                        "field_aware_boost": float(field_boost if channel == "vector" else 0.0),
                    }
            return out

        vector_norm = normalize(vector_results, channel="vector")
        bm25_norm = normalize(bm25_results, channel="bm25")
        lexical_norm = normalize(lexical_results, channel="lexical")
        sparse_norm = normalize(sparse_results, channel="sparse")

        def _attach_field_aware_signal(item: dict[str, Any], key: str) -> None:
            field_signal = vector_norm.get(key, {}).get("field_aware_signal")
            field_boost = float(vector_norm.get(key, {}).get("field_aware_boost") or 0.0)
            chunk_type = (
                vector_norm.get(key, {}).get("chunk_type")
                or bm25_norm.get(key, {}).get("chunk_type")
                or lexical_norm.get(key, {}).get("chunk_type")
                or sparse_norm.get(key, {}).get("chunk_type")
            )
            chunk_type_boost = max(
                float(vector_norm.get(key, {}).get("chunk_type_boost") or 0.0),
                float(bm25_norm.get(key, {}).get("chunk_type_boost") or 0.0),
                float(lexical_norm.get(key, {}).get("chunk_type_boost") or 0.0),
                float(sparse_norm.get(key, {}).get("chunk_type_boost") or 0.0),
            )
            if field_signal:
                item["field_aware_signal"] = str(field_signal)
            if field_boost > 0.0:
                item["field_aware_boost"] = float(field_boost)
            if chunk_type:
                item["chunk_type_signal"] = str(chunk_type)
            if chunk_type_boost > 0.0:
                item["chunk_type_boost"] = float(chunk_type_boost)

        try:
            if isinstance(self._last_channel_metrics, dict):
                field_signal_counts: Counter[str] = Counter()
                boosted = 0
                for payload in vector_norm.values():
                    signal = str(payload.get("field_aware_signal") or "body").strip().lower() or "body"
                    field_signal_counts[signal] += 1
                    if float(payload.get("field_aware_boost") or 0.0) > 0.0:
                        boosted += 1

                self._last_channel_metrics["field_aware"] = {
                    "enabled": bool(field_aware_enabled),
                    "title_boost": round(float(field_aware_title_boost), 6),
                    "heading_boost": round(float(field_aware_heading_boost), 6),
                    "max_boost": round(float(field_aware_max_boost), 6),
                    "candidates": int(len(vector_norm)),
                    "boosted_candidates": int(boosted),
                    "signals": dict(sorted((str(k), int(v)) for k, v in field_signal_counts.items())),
                }
                chunk_type_counts: Counter[str] = Counter()
                chunk_boosted = 0
                for payload in vector_norm.values():
                    signal = str(payload.get("chunk_type") or "text").strip().lower() or "text"
                    chunk_type_counts[signal] += 1
                    if float(payload.get("chunk_type_boost") or 0.0) > 0.0:
                        chunk_boosted += 1
                self._last_channel_metrics["chunk_type_weighting"] = {
                    "enabled": bool(chunk_type_weighting_enabled),
                    "preferred_chunk_type": preferred_chunk_type,
                    "match_boost": round(float(chunk_type_match_boost), 6),
                    "candidates": int(len(vector_norm)),
                    "boosted_candidates": int(chunk_boosted),
                    "signals": dict(sorted((str(k), int(v)) for k, v in chunk_type_counts.items())),
                }
        except Exception as exc:
            logger.debug("Ignoring non-critical retriever fallback failure: %s", exc)

        fusion = (fusion_strategy or "linear").lower().strip()
        if fusion in ("rrf", "reciprocal_rank_fusion"):
            def _rank_sort_key(r: dict[str, Any]) -> tuple[float, str]:
                # Deterministic ordering is important for regression replay.
                return (-float(r.get("score", 0.0) or 0.0), self._result_key(r))

            v_sorted = sorted(vector_results, key=_rank_sort_key)
            b_sorted = sorted(bm25_results, key=_rank_sort_key)
            l_sorted = sorted(lexical_results, key=_rank_sort_key)
            s_sorted = sorted(sparse_results, key=_rank_sort_key)

            v_rank: dict[str, int] = {}
            b_rank: dict[str, int] = {}
            l_rank: dict[str, int] = {}
            s_rank: dict[str, int] = {}
            for idx, r in enumerate(v_sorted, 1):
                key = self._result_key(r)
                if key not in v_rank:
                    v_rank[key] = idx
            for idx, r in enumerate(b_sorted, 1):
                key = self._result_key(r)
                if key not in b_rank:
                    b_rank[key] = idx
            for idx, r in enumerate(l_sorted, 1):
                key = self._result_key(r)
                if key not in l_rank:
                    l_rank[key] = idx
            for idx, r in enumerate(s_sorted, 1):
                key = self._result_key(r)
                if key not in s_rank:
                    s_rank[key] = idx

            k0 = int(rrf_k or 0) or int(getattr(self, "rrf_k", 60) or 60)
            k0 = max(1, k0)

            merged: dict[str, dict[str, Any]] = {}
            raw_scores: list[float] = []
            keys = sorted(set(vector_norm.keys()) | set(bm25_norm.keys()) | set(lexical_norm.keys()) | set(sparse_norm.keys()))
            for key in keys:
                v_data = vector_norm.get(key, {}).get("data")
                b_data = bm25_norm.get(key, {}).get("data")
                l_data = lexical_norm.get(key, {}).get("data")
                s_data = sparse_norm.get(key, {}).get("data")
                data = v_data or b_data or l_data or s_data
                if not data:
                    continue

                # Merge metadata from all channels (prefer existing non-empty values).
                merged_meta = dict(data.get("metadata") or {})
                for src in (v_data, b_data, l_data, s_data):
                    if not src or src is data:
                        continue
                    src_meta = src.get("metadata") or {}
                    for mk, mv in src_meta.items():
                        if mk not in merged_meta or merged_meta.get(mk) in (None, "", [], {}):
                            merged_meta[mk] = mv
                merged_data = dict(data)
                merged_data["metadata"] = merged_meta
                if not merged_data.get("chunk_id"):
                    for src in (v_data, b_data, l_data, s_data):
                        if src and src.get("chunk_id"):
                            merged_data["chunk_id"] = src.get("chunk_id")
                            break
                data = merged_data

                vr = v_rank.get(key)
                br = b_rank.get(key)
                lr = l_rank.get(key)
                sr = s_rank.get(key)
                rrf_raw = (1.0 / (k0 + vr)) if vr else 0.0
                rrf_raw += (1.0 / (k0 + br)) if br else 0.0
                rrf_raw += (1.0 / (k0 + lr)) if lr else 0.0
                rrf_raw += (1.0 / (k0 + sr)) if sr else 0.0
                raw_scores.append(float(rrf_raw))

                merged[key] = {
                    **data,
                    "vector_score": float(vector_norm.get(key, {}).get("score", 0.0) or 0.0),
                    "bm25_score": float(bm25_norm.get(key, {}).get("score", 0.0) or 0.0),
                    "lexical_score": float(lexical_norm.get(key, {}).get("score", 0.0) or 0.0),
                    "sparse_score": float(sparse_norm.get(key, {}).get("score", 0.0) or 0.0),
                    "rrf_score_raw": float(rrf_raw),
                    "rrf_k": k0,
                    "rrf_rank_vector": vr,
                    "rrf_rank_bm25": br,
                    "rrf_rank_lexical": lr,
                    "rrf_rank_sparse": sr,
                    "fusion_strategy": "rrf",
                    "score": float(rrf_raw),
                }
                _attach_field_aware_signal(merged[key], key)

            if merged:
                min_s = min(raw_scores) if raw_scores else 0.0
                max_s = max(raw_scores) if raw_scores else 0.0
                rng = max_s - min_s if max_s > min_s else 1.0
                for item in merged.values():
                    raw = float(item.get("rrf_score_raw", 0.0) or 0.0)
                    item["score"] = (raw - min_s) / rng

            def _sort_key(item: dict[str, Any]) -> tuple[float, float, float, float, float, float, str]:
                return (
                    -float(item.get("score", 0.0) or 0.0),
                    -float(item.get("rrf_score_raw", 0.0) or 0.0),
                    -float(item.get("vector_score", 0.0) or 0.0),
                    -float(item.get("bm25_score", 0.0) or 0.0),
                    -float(item.get("lexical_score", 0.0) or 0.0),
                    -float(item.get("sparse_score", 0.0) or 0.0),
                    self._result_key(item),
                )

            return sorted(merged.values(), key=_sort_key)

        if fusion in ("budgeted_rrf", "budget_rrf"):
            def _rank_sort_key(r: dict[str, Any]) -> tuple[float, str]:
                # Deterministic ordering is important for regression replay.
                return (-float(r.get("score", 0.0) or 0.0), self._result_key(r))

            v_sorted = sorted(vector_results, key=_rank_sort_key)
            b_sorted = sorted(bm25_results, key=_rank_sort_key)
            l_sorted = sorted(lexical_results, key=_rank_sort_key)
            s_sorted = sorted(sparse_results, key=_rank_sort_key)

            v_rank: dict[str, int] = {}
            b_rank: dict[str, int] = {}
            l_rank: dict[str, int] = {}
            s_rank: dict[str, int] = {}
            for idx, r in enumerate(v_sorted, 1):
                key = self._result_key(r)
                if key not in v_rank:
                    v_rank[key] = idx
            for idx, r in enumerate(b_sorted, 1):
                key = self._result_key(r)
                if key not in b_rank:
                    b_rank[key] = idx
            for idx, r in enumerate(l_sorted, 1):
                key = self._result_key(r)
                if key not in l_rank:
                    l_rank[key] = idx
            for idx, r in enumerate(s_sorted, 1):
                key = self._result_key(r)
                if key not in s_rank:
                    s_rank[key] = idx

            def _rank_score(rank_map: dict[str, int], key: str) -> float:
                rnk = rank_map.get(key)
                if not rnk:
                    return 0.0
                rnk = int(rnk)
                if rnk <= 0:
                    return 0.0
                return 1.0 / float(rnk)

            def _coerce_budgets(raw: Any) -> dict[str, int]:
                if not isinstance(raw, dict):
                    return {}
                out0: dict[str, int] = {}
                for k, v in raw.items():
                    key = str(k or "").strip().lower()
                    if not key:
                        continue
                    try:
                        iv = int(v) if v is not None else 0
                    except (TypeError, ValueError, AttributeError):
                        continue
                    out0[key] = max(0, iv)
                return out0

            def _coerce_min_scores(raw: Any) -> dict[str, float]:
                if not isinstance(raw, dict):
                    return {}
                out0: dict[str, float] = {}
                for k, v in raw.items():
                    key = str(k or "").strip().lower()
                    if not key:
                        continue
                    try:
                        fv = float(v) if v is not None else 0.0
                    except (TypeError, ValueError, AttributeError):
                        continue
                    out0[key] = max(0.0, min(1.0, fv))
                return out0

            # Determine budgets (quotas) for the top_k prefix.
            k_prefix = int(top_k or 0) or int(getattr(self, "k", 0) or 0) or 10
            k_prefix = max(1, k_prefix)

            budgets = _coerce_budgets(getattr(self, "fusion_budgets", None))
            if not budgets:
                # Default: ensure cross-channel recall in the visible prefix.
                # - vector: ~50%
                # - keyword (bm25 + lexical): remaining, split evenly
                # - sparse: 0 by default (can be enabled via fusion_budgets)
                vec = int(math.ceil(k_prefix * 0.5))
                keyword = max(0, k_prefix - vec)
                bm = int(math.ceil(keyword * 0.5)) if keyword else 0
                lex = max(0, keyword - bm)
                budgets = {"vector": vec, "bm25": bm, "lexical": lex, "sparse": 0}

            min_scores = _coerce_min_scores(getattr(self, "fusion_min_scores", None))

            k0 = int(rrf_k or 0) or int(getattr(self, "rrf_k", 60) or 60)
            k0 = max(1, k0)

            merged: dict[str, dict[str, Any]] = {}
            raw_scores: list[float] = []
            keys = sorted(set(vector_norm.keys()) | set(bm25_norm.keys()) | set(lexical_norm.keys()) | set(sparse_norm.keys()))

            def _candidate_eligible(key: str) -> bool:
                # Candidate must have at least one channel where it meets that channel's min score (if configured).
                for ch, rmap in (("vector", v_rank), ("bm25", b_rank), ("lexical", l_rank), ("sparse", s_rank)):
                    rs = _rank_score(rmap, key)
                    if rs <= 0.0:
                        continue
                    th = min_scores.get(ch)
                    if th is None or rs >= float(th):
                        return True
                return False

            for key in keys:
                v_data = vector_norm.get(key, {}).get("data")
                b_data = bm25_norm.get(key, {}).get("data")
                l_data = lexical_norm.get(key, {}).get("data")
                s_data = sparse_norm.get(key, {}).get("data")
                data = v_data or b_data or l_data or s_data
                if not data:
                    continue

                # Merge metadata from all channels (prefer existing non-empty values).
                merged_meta = dict(data.get("metadata") or {})
                for src in (v_data, b_data, l_data, s_data):
                    if not src or src is data:
                        continue
                    src_meta = src.get("metadata") or {}
                    for mk, mv in src_meta.items():
                        if mk not in merged_meta or merged_meta.get(mk) in (None, "", [], {}):
                            merged_meta[mk] = mv
                merged_data = dict(data)
                merged_data["metadata"] = merged_meta
                if not merged_data.get("chunk_id"):
                    for src in (v_data, b_data, l_data, s_data):
                        if src and src.get("chunk_id"):
                            merged_data["chunk_id"] = src.get("chunk_id")
                            break
                data = merged_data

                vr = v_rank.get(key)
                br = b_rank.get(key)
                lr = l_rank.get(key)
                sr = s_rank.get(key)
                rrf_raw = (1.0 / (k0 + vr)) if vr else 0.0
                rrf_raw += (1.0 / (k0 + br)) if br else 0.0
                rrf_raw += (1.0 / (k0 + lr)) if lr else 0.0
                rrf_raw += (1.0 / (k0 + sr)) if sr else 0.0
                raw_scores.append(float(rrf_raw))

                merged[key] = {
                    **data,
                    "vector_score": float(vector_norm.get(key, {}).get("score", 0.0) or 0.0),
                    "bm25_score": float(bm25_norm.get(key, {}).get("score", 0.0) or 0.0),
                    "lexical_score": float(lexical_norm.get(key, {}).get("score", 0.0) or 0.0),
                    "sparse_score": float(sparse_norm.get(key, {}).get("score", 0.0) or 0.0),
                    "vector_rank_score": float(_rank_score(v_rank, key)),
                    "bm25_rank_score": float(_rank_score(b_rank, key)),
                    "lexical_rank_score": float(_rank_score(l_rank, key)),
                    "sparse_rank_score": float(_rank_score(s_rank, key)),
                    "rrf_score_raw": float(rrf_raw),
                    "rrf_k": k0,
                    "rrf_rank_vector": vr,
                    "rrf_rank_bm25": br,
                    "rrf_rank_lexical": lr,
                    "rrf_rank_sparse": sr,
                    "fusion_strategy": "budgeted_rrf",
                    "score": float(rrf_raw),
                }
                _attach_field_aware_signal(merged[key], key)

            if merged:
                min_s = min(raw_scores) if raw_scores else 0.0
                max_s = max(raw_scores) if raw_scores else 0.0
                rng = max_s - min_s if max_s > min_s else 1.0
                for item in merged.values():
                    raw = float(item.get("rrf_score_raw", 0.0) or 0.0)
                    item["score"] = (raw - min_s) / rng

            def _sort_key(item: dict[str, Any]) -> tuple[float, float, float, float, float, float, str]:
                return (
                    -float(item.get("score", 0.0) or 0.0),
                    -float(item.get("rrf_score_raw", 0.0) or 0.0),
                    -float(item.get("vector_rank_score", 0.0) or 0.0),
                    -float(item.get("bm25_rank_score", 0.0) or 0.0),
                    -float(item.get("lexical_rank_score", 0.0) or 0.0),
                    -float(item.get("sparse_rank_score", 0.0) or 0.0),
                    self._result_key(item),
                )

            all_sorted = sorted(merged.values(), key=_sort_key)

            # Build a top_k prefix that enforces budgets/quotas but still orders by fused score.
            selected_keys: list[str] = []
            used: set[str] = set()
            picked_by_channel: dict[str, int] = {"vector": 0, "bm25": 0, "lexical": 0, "sparse": 0, "fill": 0}

            def _select_from_channel(channel: str, sorted_results: list[dict[str, Any]], rank_map: dict[str, int]) -> None:
                quota = int(budgets.get(channel, 0) or 0)
                if quota <= 0:
                    return
                picked = 0
                th = min_scores.get(channel)
                for rr in sorted_results:
                    if picked >= quota:
                        break
                    key = self._result_key(rr)
                    if key in used:
                        continue
                    rs = _rank_score(rank_map, key)
                    if rs <= 0.0:
                        continue
                    if th is not None and rs < float(th):
                        # Rank scores are monotonic decreasing within a channel; can stop early.
                        break
                    if not _candidate_eligible(key):
                        continue
                    used.add(key)
                    selected_keys.append(key)
                    picked += 1
                    try:
                        picked_by_channel[channel] = int(picked_by_channel.get(channel, 0) or 0) + 1
                    except Exception as exc:
                        logger.debug("Ignoring non-critical retriever fallback failure: %s", exc)

            _select_from_channel("vector", v_sorted, v_rank)
            _select_from_channel("bm25", b_sorted, b_rank)
            _select_from_channel("lexical", l_sorted, l_rank)
            _select_from_channel("sparse", s_sorted, s_rank)

            if len(selected_keys) < k_prefix:
                for item in all_sorted:
                    if len(selected_keys) >= k_prefix:
                        break
                    key = self._result_key(item)
                    if key in used:
                        continue
                    if not _candidate_eligible(key):
                        continue
                    used.add(key)
                    selected_keys.append(key)
                    try:
                        picked_by_channel["fill"] = int(picked_by_channel.get("fill", 0) or 0) + 1
                    except Exception as exc:
                        logger.debug("Ignoring non-critical retriever fallback failure: %s", exc)

            selected_set = set(selected_keys)
            prefix = [item for item in all_sorted if self._result_key(item) in selected_set]
            rest = [item for item in all_sorted if self._result_key(item) not in selected_set]

            # Best-effort: surface fusion budget behavior into retriever_debug.channels for diagnostics.
            # PII-safe: only small numeric counters and low-cardinality settings.
            try:
                eligible_total = 0
                for key in keys:
                    if _candidate_eligible(key):
                        eligible_total += 1

                budgets_out = dict(sorted((str(k), int(v or 0)) for k, v in (budgets or {}).items()))
                min_scores_out = dict(sorted((str(k), float(v or 0.0)) for k, v in (min_scores or {}).items()))
                picked_out = {k: int(picked_by_channel.get(k, 0) or 0) for k in ("vector", "bm25", "lexical", "sparse", "fill")}

                if isinstance(self._last_channel_metrics, dict):
                    self._last_channel_metrics["fusion_budgeted_rrf"] = {
                        "k_prefix": int(k_prefix),
                        "rrf_k": int(k0),
                        "budgets": budgets_out,
                        "min_scores": min_scores_out or None,
                        "eligible_total": int(eligible_total),
                        "selected_prefix": int(len(selected_keys)),
                        "picked_by_channel": picked_out,
                    }
            except Exception as exc:
                logger.debug("Ignoring non-critical retriever fallback failure: %s", exc)
            return prefix + rest

        if fusion in ("weighted", "weighted_linear", "weighted_sum"):
            def _coerce_weights(raw: Any) -> dict[str, float]:
                if not isinstance(raw, dict):
                    return {}
                allowed = {"vector", "bm25", "lexical", "sparse"}
                out0: dict[str, float] = {}
                for k, v in raw.items():
                    key = str(k or "").strip().lower()
                    if not key or key not in allowed:
                        continue
                    try:
                        w = float(v)
                    except (TypeError, ValueError, AttributeError):
                        continue
                    if w <= 0.0:
                        continue
                    out0[key] = float(w)
                return out0

            weights_raw = _coerce_weights(getattr(self, "fusion_weights", None))
            w_sum = sum(float(x) for x in weights_raw.values())
            if w_sum <= 0.0:
                # Safe fallback: behave like linear fusion when weights are not configured.
                fusion = "linear"
            else:
                weights = {k: (float(v) / w_sum) for k, v in weights_raw.items()}

                merged: dict[str, dict[str, Any]] = {}
                keys = sorted(
                    set(vector_norm.keys()) | set(bm25_norm.keys()) | set(lexical_norm.keys()) | set(sparse_norm.keys())
                )
                for key in keys:
                    v_score = float(vector_norm.get(key, {}).get("score", 0.0) or 0.0)
                    b_score = float(bm25_norm.get(key, {}).get("score", 0.0) or 0.0)
                    l_score = float(lexical_norm.get(key, {}).get("score", 0.0) or 0.0)
                    s_score = float(sparse_norm.get(key, {}).get("score", 0.0) or 0.0)
                    v_data = vector_norm.get(key, {}).get("data")
                    b_data = bm25_norm.get(key, {}).get("data")
                    l_data = lexical_norm.get(key, {}).get("data")
                    s_data = sparse_norm.get(key, {}).get("data")
                    data = v_data or b_data or l_data or s_data
                    if not data:
                        continue

                    # Merge metadata from all channels (e.g., img_id may only exist in BM25/DB metadata).
                    merged_meta = dict(data.get("metadata") or {})
                    for src in (v_data, b_data, l_data, s_data):
                        if not src or src is data:
                            continue
                        src_meta = src.get("metadata") or {}
                        for mk, mv in src_meta.items():
                            if mk not in merged_meta or merged_meta.get(mk) in (None, "", [], {}):
                                merged_meta[mk] = mv
                    merged_data = dict(data)
                    merged_data["metadata"] = merged_meta
                    if not merged_data.get("chunk_id"):
                        for src in (v_data, b_data, l_data, s_data):
                            if src and src.get("chunk_id"):
                                merged_data["chunk_id"] = src.get("chunk_id")
                                break
                    data = merged_data

                    fused_score = (
                        float(weights.get("vector", 0.0) or 0.0) * float(v_score)
                        + float(weights.get("bm25", 0.0) or 0.0) * float(b_score)
                        + float(weights.get("lexical", 0.0) or 0.0) * float(l_score)
                        + float(weights.get("sparse", 0.0) or 0.0) * float(s_score)
                    )

                    merged[key] = {
                        **data,
                        "vector_score": float(v_score),
                        "bm25_score": float(b_score),
                        "lexical_score": float(l_score),
                        "sparse_score": float(s_score),
                        "fusion_strategy": "weighted",
                        "score": float(fused_score),
                    }
                    _attach_field_aware_signal(merged[key], key)

                # Best-effort: surface weights used into retriever_debug.channels for diagnostics.
                try:
                    if isinstance(self._last_channel_metrics, dict):
                        weights_out = dict(sorted((k, round(float(v), 6)) for k, v in (weights or {}).items()))
                        sig = ",".join([f"{k}:{weights_out.get(k, 0.0):.6f}" for k in sorted(weights_out.keys())])
                        self._last_channel_metrics["fusion_weighted"] = {
                            "weights": weights_out,
                            "weights_hash": stable_hash(sig, length=16) if sig else None,
                        }
                except Exception as exc:
                    logger.debug("Ignoring non-critical retriever fallback failure: %s", exc)

                def _sort_key(item: dict[str, Any]) -> tuple[float, float, float, float, float, str]:
                    return (
                        -float(item.get("score", 0.0) or 0.0),
                        -float(item.get("vector_score", 0.0) or 0.0),
                        -float(item.get("bm25_score", 0.0) or 0.0),
                        -float(item.get("lexical_score", 0.0) or 0.0),
                        -float(item.get("sparse_score", 0.0) or 0.0),
                        self._result_key(item),
                    )

                return sorted(merged.values(), key=_sort_key)

        merged: dict[str, dict[str, Any]] = {}
        keys = sorted(set(vector_norm.keys()) | set(bm25_norm.keys()) | set(lexical_norm.keys()) | set(sparse_norm.keys()))
        for key in keys:
            v_score = vector_norm.get(key, {}).get("score", 0.0)
            b_score = bm25_norm.get(key, {}).get("score", 0.0)
            l_score = lexical_norm.get(key, {}).get("score", 0.0)
            s_score = sparse_norm.get(key, {}).get("score", 0.0)
            v_data = vector_norm.get(key, {}).get("data")
            b_data = bm25_norm.get(key, {}).get("data")
            l_data = lexical_norm.get(key, {}).get("data")
            s_data = sparse_norm.get(key, {}).get("data")
            data = v_data or b_data or l_data or s_data
            if not data:
                continue

            # Merge metadata from all channels (e.g., img_id may only exist in BM25/DB metadata).
            merged_meta = dict(data.get("metadata") or {})
            for src in (v_data, b_data, l_data, s_data):
                if not src or src is data:
                    continue
                src_meta = src.get("metadata") or {}
                for mk, mv in src_meta.items():
                    if mk not in merged_meta or merged_meta.get(mk) in (None, "", [], {}):
                        merged_meta[mk] = mv
            merged_data = dict(data)
            merged_data["metadata"] = merged_meta
            if not merged_data.get("chunk_id"):
                for src in (v_data, b_data, l_data, s_data):
                    if src and src.get("chunk_id"):
                        merged_data["chunk_id"] = src.get("chunk_id")
                        break
            data = merged_data

            has_v = key in vector_norm
            has_b = key in bm25_norm
            has_l = key in lexical_norm
            has_s = key in sparse_norm
            keyword_score = max(float(b_score), float(l_score), float(s_score))
            if has_v and (has_b or has_l or has_s):
                fused_score = alpha * float(v_score) + (1 - alpha) * float(keyword_score)
            elif has_v:
                fused_score = float(v_score)
            else:
                fused_score = float(keyword_score)

            merged[key] = {
                **data,
                "vector_score": float(v_score),
                "bm25_score": float(b_score),
                "lexical_score": float(l_score),
                "sparse_score": float(s_score),
                "fusion_strategy": "linear",
                "score": fused_score,
            }
            _attach_field_aware_signal(merged[key], key)

        def _sort_key(item: dict[str, Any]) -> tuple[float, float, float, float, float, str]:
            return (
                -float(item.get("score", 0.0) or 0.0),
                -float(item.get("vector_score", 0.0) or 0.0),
                -float(item.get("bm25_score", 0.0) or 0.0),
                -float(item.get("lexical_score", 0.0) or 0.0),
                -float(item.get("sparse_score", 0.0) or 0.0),
                self._result_key(item),
            )

        return sorted(merged.values(), key=_sort_key)

    def _weight_rerank(
        self,
        query: str,
        documents: list[dict[str, Any]],
        vector_weight: float = 0.6,
        keyword_weight: float = 0.4,
    ) -> list[dict[str, Any]]:
        """Vector score + keyword TF-IDF cosine linear weighting."""
        if not documents:
            return documents

        query_tokens = self._bm25_tokenize(query)
        doc_tokens_list = [self._bm25_tokenize(doc.get("content", "")) for doc in documents]

        all_tokens = {tok for tokens in doc_tokens_list for tok in tokens}
        if not all_tokens:
            return documents

        doc_count = len(documents)
        token_idf: dict[str, float] = {}
        for tok in all_tokens:
            df = sum(1 for tokens in doc_tokens_list if tok in tokens)
            token_idf[tok] = math.log((1 + doc_count) / (1 + df)) + 1

        def tfidf_vec(tokens: list[str]) -> dict[str, float]:
            tf = Counter(tokens)
            return {t: tf[t] * token_idf.get(t, 0.0) for t in tf}

        query_vec = tfidf_vec(query_tokens)
        doc_vecs = [tfidf_vec(tokens) for tokens in doc_tokens_list]

        def cosine(a: dict[str, float], b: dict[str, float]) -> float:
            if not a or not b:
                return 0.0
            common = set(a.keys()) & set(b.keys())
            num = sum(a[t] * b[t] for t in common)
            denom = math.sqrt(sum(v * v for v in a.values())) * math.sqrt(sum(v * v for v in b.values()))
            return num / denom if denom else 0.0

        keyword_scores = [cosine(query_vec, v) for v in doc_vecs]

        reranked: list[dict[str, Any]] = []
        for doc, kw_score in zip(documents, keyword_scores, strict=False):
            vec_score = doc.get("vector_score", doc.get("score", 0.0))
            final_score = vector_weight * float(vec_score) + keyword_weight * float(kw_score)
            new_doc = dict(doc)
            new_doc["keyword_score"] = float(kw_score)
            new_doc["score"] = float(final_score)
            reranked.append(new_doc)

        reranked.sort(key=lambda x: x["score"], reverse=True)
        return reranked

    def _mmr_rerank(
        self,
        documents: list[dict[str, Any]],
        query: str,
        top_k: int,
        lambda_mult: float = 0.7,
    ) -> list[dict[str, Any]]:
        """
        Simple MMR (Maximal Marginal Relevance) reranking:
        max lambda*sim(query, doc) - (1-lambda)*max sim(doc, selected)
        Uses bag-of-words Jaccard approximation, lightweight with no extra dependencies.
        """
        if not documents:
            return documents

        lambda_mult = max(min(lambda_mult, 1.0), 0.0)
        selected: list[dict[str, Any]] = []
        candidates = list(documents)
        # Pre-cache tokens to avoid multiple tokenizations
        tokens_map = {id(doc): self._tokenize_for_similarity(doc.get("content", "")) for doc in candidates}

        def doc_similarity(doc_a: dict[str, Any], doc_b: dict[str, Any]) -> float:
            tokens_a = tokens_map.get(id(doc_a), set())
            tokens_b = tokens_map.get(id(doc_b), set())
            if not tokens_a or not tokens_b:
                return 0.0
            inter = tokens_a & tokens_b
            union = tokens_a | tokens_b
            return len(inter) / len(union) if union else 0.0

        while candidates and len(selected) < top_k:
            best = None
            best_score = -1e9
            for i, doc in enumerate(candidates):
                relevance = float(doc.get("score", 0.0))
                diversity_penalty = 0.0
                if selected:
                    sel_sims = [doc_similarity(doc, s) for s in selected]
                    diversity_penalty = max(sel_sims) if sel_sims else 0.0
                mmr_score = lambda_mult * relevance - (1 - lambda_mult) * diversity_penalty
                if mmr_score > best_score:
                    best_score = mmr_score
                    best = (i, doc)

            if best is None:
                break
            idx, doc = best
            selected.append(doc)
            candidates.pop(idx)

        return selected


# Global instance
hybrid_retriever = HybridRetriever()

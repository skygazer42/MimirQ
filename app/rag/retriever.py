"""
Hybrid Retriever: Vector retrieval + BM25 + optional MMR diversity reranking.
Reference: RAG_Agent example repository. Retrieval modes and reranking strategies are configurable.
"""

import heapq
import math
import re
import threading
import time
from collections import Counter, OrderedDict
from typing import Any, Dict, List, Optional
from uuid import UUID

import jieba
from langchain_community.retrievers.bm25 import BM25Retriever
from langchain_core.callbacks import AsyncCallbackManagerForRetrieverRun, CallbackManagerForRetrieverRun
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from pydantic import ConfigDict, PrivateAttr
from sqlalchemy import tuple_
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.document import Document as DBDocument
from app.models.document import DocumentChunk
from app.rag.core.filters import match_metadata_filter
from app.rag.core.hashing import stable_hash
from app.rag.core.logging import get_logger
from app.rag.embedding.utils import current_embedding_space_hash
from app.rag.preprocessing.stopwords import STOPWORDS
from app.rag.preprocessing.tokenization import tokenize_for_bm25
from app.rag.reranker.factory import get_reranker
from app.rag.reranker.types import RerankCandidate
from app.storage.vector.factory import get_vector_store

logger = get_logger("rag.retriever")


class HybridRetriever(BaseRetriever):
    """Hybrid Retriever: Vector + Keyword BM25, optional MMR reranking."""

    k: int = 5
    score_threshold: float = settings.SIMILARITY_THRESHOLD
    alpha: float = 0.6
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
    dedup_enabled: bool = settings.RETRIEVAL_DEDUP_ENABLED
    dedup_jaccard_threshold: float = settings.RETRIEVAL_DEDUP_JACCARD_THRESHOLD
    dedup_max_compare: int = settings.RETRIEVAL_DEDUP_MAX_COMPARE
    max_chunks_per_doc: int = settings.RETRIEVAL_MAX_CHUNKS_PER_DOC
    min_distinct_docs: int = settings.RETRIEVAL_MIN_DISTINCT_DOCS
    tenant_id: Optional[UUID] = None
    # Optional: used for candidate-level ACL trimming when retrieval is not pre-scoped
    # by document_ids. When set, results are filtered fail-closed.
    account_id: Optional[str] = None
    # Optional: dataset scope. When set, results are restricted to documents within the dataset.
    dataset_id: Optional[UUID] = None
    document_ids: Optional[List[UUID]] = None
    # Metadata filtering
    metadata_filter: Optional[Dict[str, Any]] = None
    metadata_filter_enabled: bool = getattr(settings, "RETRIEVAL_METADATA_FILTER_ENABLED", True)

    model_config = ConfigDict(arbitrary_types_allowed=True)

    _bm25_retrievers: Dict[str, BM25Retriever] = PrivateAttr(default_factory=dict)
    _bm25_docs: Dict[str, List[Document]] = PrivateAttr(default_factory=dict)
    _bm25_doc_ids: Dict[str, set[str]] = PrivateAttr(default_factory=dict)
    _chunk_id_lookup: Dict[str, Dict[str, str]] = PrivateAttr(default_factory=dict)
    _bm25_build_locks: Dict[str, threading.Lock] = PrivateAttr(default_factory=dict)
    # LRU order for per-tenant BM25 caches (prevents unbounded growth in multi-tenant deployments).
    _bm25_cache_order: "OrderedDict[str, None]" = PrivateAttr(default_factory=OrderedDict)
    _bm25_cache_lock: threading.Lock = PrivateAttr(default_factory=threading.Lock)
    # Best-effort debug metrics for the last retrieval call (per retriever instance).
    # Used by debug endpoints / observability to expose trimming/overfetch behavior.
    _last_debug_metrics: Dict[str, Any] = PrivateAttr(default_factory=dict)

    def _refresh_bm25_doc_ids(self, tenant_key: str, docs: List[Document] | None) -> None:
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

    def _tenant_key(self, tenant_id: Optional[UUID]) -> str:
        return str(tenant_id or settings.DEFAULT_TENANT_ID)

    def _get_bm25_build_lock(self, tenant_key: str) -> threading.Lock:
        lock = self._bm25_build_locks.get(tenant_key)
        if lock is None:
            lock = threading.Lock()
            self._bm25_build_locks[tenant_key] = lock
        return lock

    def _bm25_cache_max_tenants(self) -> int:
        try:
            return max(0, int(getattr(settings, "BM25_CACHE_MAX_TENANTS", 0) or 0))
        except Exception:
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

        for tenant in evicted:
            self._bm25_retrievers.pop(tenant, None)
            self._bm25_docs.pop(tenant, None)
            self._bm25_doc_ids.pop(tenant, None)
            self._chunk_id_lookup.pop(tenant, None)
            self._bm25_build_locks.pop(tenant, None)

        if evicted:
            logger.info("BM25 cache evicted %s tenants (max=%s)", len(evicted), max_tenants)

    def _lazy_build_bm25_index(
        self,
        *,
        tenant_id: Optional[UUID],
        document_ids: Optional[List[UUID]],
    ) -> bool:
        """Build BM25 index on-demand to mitigate cold-start in multi-process deployments."""
        if not bool(getattr(settings, "BM25_INDEX_ENABLED", True)):
            return False
        if not bool(getattr(settings, "BM25_LAZY_BUILD_ENABLED", True)):
            return False

        tenant_uuid: Optional[UUID] = tenant_id
        if tenant_uuid is None:
            try:
                tenant_uuid = UUID(str(getattr(settings, "DEFAULT_TENANT_ID", "") or ""))
            except Exception:
                tenant_uuid = None
        if tenant_uuid is None:
            return False

        tenant_key = self._tenant_key(tenant_uuid)
        existing_retriever = self._bm25_retrievers.get(tenant_key)
        existing_docs = self._bm25_docs.get(tenant_key)
        if existing_retriever is not None and existing_docs is not None:
            # If a request scopes to specific documents, ensure those docs are covered by the current cache.
            # Lazy-built indices may have been created from a subset (e.g. first query after restart).
            if document_ids:
                indexed = self._bm25_doc_ids.get(tenant_key)
                if indexed is None:
                    self._refresh_bm25_doc_ids(tenant_key, existing_docs)
                    indexed = self._bm25_doc_ids.get(tenant_key) or set()
                requested = {str(did) for did in document_ids if did is not None}
                missing = requested - set(indexed or set())
                if not missing:
                    self._touch_bm25_cache(tenant_key)
                    return True
            else:
                self._touch_bm25_cache(tenant_key)
                return True

        lock = self._get_bm25_build_lock(tenant_key)
        with lock:
            existing_retriever = self._bm25_retrievers.get(tenant_key)
            existing_docs = self._bm25_docs.get(tenant_key)
            if existing_retriever is not None and existing_docs is not None:
                if document_ids:
                    indexed = self._bm25_doc_ids.get(tenant_key)
                    if indexed is None:
                        self._refresh_bm25_doc_ids(tenant_key, existing_docs)
                        indexed = self._bm25_doc_ids.get(tenant_key) or set()
                    requested = {str(did) for did in document_ids if did is not None}
                    missing = requested - set(indexed or set())
                    if not missing:
                        self._touch_bm25_cache(tenant_key)
                        return True
                else:
                    self._touch_bm25_cache(tenant_key)
                    return True

            full_tenant = bool(getattr(settings, "BM25_LAZY_BUILD_FULL_TENANT", False))
            if not document_ids and not full_tenant:
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
                    except TypeError:
                        pass
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
                except Exception:
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
                    indexed = self._bm25_doc_ids.get(tenant_key)
                    if indexed is None:
                        self._refresh_bm25_doc_ids(tenant_key, existing_docs)
                        indexed = self._bm25_doc_ids.get(tenant_key) or set()
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
                                .filter(DocumentChunk.tenant_id == tenant_uuid)
                                .filter(DocumentChunk.document_id.in_(document_ids))
                                .order_by(DocumentChunk.document_id.asc(), DocumentChunk.chunk_index.asc())
                            )
                            q = _maybe_call(q, "enable_eagerloads", False)
                            q = _maybe_call(q, "execution_options", stream_results=True)
                            if max_chunks:
                                q = q.limit(max_chunks)
                            docs: List[Document] = []
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
                            self._build_bm25_index_from_documents(docs, tenant_id=tenant_uuid)
                            logger.info(
                                "BM25 lazy-built (scoped rebuild) %s chunks for tenant %s missing_docs=%s cap=%s",
                                len(docs),
                                tenant_key,
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
                        bm25_docs: List[Document] = []
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
                    .filter(DocumentChunk.tenant_id == tenant_uuid)
                )
                q = _maybe_call(q, "enable_eagerloads", False)
                q = _maybe_call(q, "execution_options", stream_results=True)
                if document_ids:
                    q = q.filter(DocumentChunk.document_id.in_(document_ids))
                q = q.order_by(DocumentChunk.document_id.asc(), DocumentChunk.chunk_index.asc())
                if max_chunks:
                    q = q.limit(max_chunks)
                docs: List[Document] = []
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
                self._build_bm25_index_from_documents(docs, tenant_id=tenant_uuid)
                logger.info(
                    "BM25 lazy-built %s chunks for tenant %s (doc_ids=%s)",
                    len(docs),
                    tenant_key,
                    len(document_ids) if document_ids else 0,
                )
                return True
            except Exception as exc:
                logger.warning("BM25 lazy build failed for tenant %s: %s", tenant_key, str(exc)[:200])
                return False
            finally:
                try:
                    db.close()
                except Exception:
                    pass

    @staticmethod
    def _bm25_tokenize(text: str) -> List[str]:
        """Tokenize text for BM25 (shared)."""
        return tokenize_for_bm25(text)

    def build_bm25_index(self, chunks: List[DocumentChunk], tenant_id: Optional[UUID] = None):
        """Build/rebuild BM25 index."""
        if not chunks:
            return

        docs: List[Document] = []
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

    def _build_bm25_index_from_documents(self, docs: List[Document], *, tenant_id: Optional[UUID] = None) -> None:
        """Build BM25 from LangChain Document list (avoids dependency on ORM objects)."""
        if not docs:
            return
        tenant_key = self._tenant_key(tenant_id)
        retriever = BM25Retriever.from_documents(docs, preprocess_func=self._bm25_tokenize, k=10)
        self._bm25_retrievers[tenant_key] = retriever
        self._bm25_docs[tenant_key] = docs
        self._refresh_bm25_doc_ids(tenant_key, docs)
        lookup: Dict[str, str] = {}
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
        self._chunk_id_lookup[tenant_key] = lookup
        self._touch_bm25_cache(tenant_key)
        logger.info("BM25 index built with %s chunks for tenant %s", len(docs), tenant_key)

    def build_bm25_index_from_db(
        self,
        db: Session,
        *,
        tenant_id: UUID,
        document_ids: Optional[List[UUID]] = None,
        max_chunks: int = 0,
        batch_size: int = 2000,
    ) -> int:
        """
        Build BM25 from DB with streaming to avoid memory spikes from large ORM list via `.all()`.
        Still holds BM25 docs in memory (BM25 itself requires this), but avoids ORM object overhead.
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
            .filter(DocumentChunk.tenant_id == tenant_id)
            .order_by(DocumentChunk.document_id.asc(), DocumentChunk.chunk_index.asc())
            .enable_eagerloads(False)
            .execution_options(stream_results=True)
        )
        if document_ids:
            q = q.filter(DocumentChunk.document_id.in_(document_ids))
        if max_chunks and int(max_chunks) > 0:
            q = q.limit(int(max_chunks))

        docs: List[Document] = []
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
            docs.append(Document(page_content=content or "", id=str(chunk_id), metadata=meta))

        self._build_bm25_index_from_documents(docs, tenant_id=tenant_id)
        return len(docs)

    def upsert_bm25_documents(self, docs: List[Document], tenant_id: Optional[UUID] = None):
        """
        Incrementally update BM25 index (avoids full DB scan each time).
        Note: BM25Retriever itself doesn't support incremental training, so we merge in-memory and rebuild.
        This still significantly reduces DB query overhead, suitable for large-scale knowledge bases.
        """
        if not docs:
            return
        tenant_key = self._tenant_key(tenant_id)
        existing = self._bm25_docs.get(tenant_key) or []
        merged: Dict[str, Document] = {str(d.id): d for d in existing if d.id is not None}
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
        self._bm25_retrievers[tenant_key] = retriever
        self._bm25_docs[tenant_key] = merged_docs
        self._refresh_bm25_doc_ids(tenant_key, merged_docs)
        lookup: Dict[str, str] = {}
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
        self._chunk_id_lookup[tenant_key] = lookup
        self._touch_bm25_cache(tenant_key)
        logger.info("BM25 index updated to %s chunks for tenant %s", len(merged_docs), tenant_key)

    def remove_document_from_bm25_index(self, document_id: UUID, tenant_id: Optional[UUID] = None):
        """Remove all chunks of a specified document from the BM25 index."""
        tenant_key = self._tenant_key(tenant_id)
        existing = self._bm25_docs.get(tenant_key) or []
        if not existing:
            return
        filtered = [d for d in existing if str((d.metadata or {}).get("document_id")) != str(document_id)]
        retriever = BM25Retriever.from_documents(
            filtered,
            preprocess_func=self._bm25_tokenize,
            k=10,
        ) if filtered else None
        if retriever is None:
            self._bm25_retrievers.pop(tenant_key, None)
            self._bm25_docs.pop(tenant_key, None)
            self._bm25_doc_ids.pop(tenant_key, None)
            self._chunk_id_lookup.pop(tenant_key, None)
            self._bm25_build_locks.pop(tenant_key, None)
            with self._bm25_cache_lock:
                self._bm25_cache_order.pop(tenant_key, None)
            logger.info("BM25 index cleared for tenant %s", tenant_key)
            return
        self._bm25_retrievers[tenant_key] = retriever
        self._bm25_docs[tenant_key] = filtered
        self._refresh_bm25_doc_ids(tenant_key, filtered)
        lookup: Dict[str, str] = {}
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
        self._chunk_id_lookup[tenant_key] = lookup
        self._touch_bm25_cache(tenant_key)
        logger.info("BM25 index removed document %s for tenant %s", document_id, tenant_key)

    def remove_from_bm25_index_by_metadata_filter(
        self,
        *,
        tenant_id: Optional[UUID] = None,
        metadata_filter: Optional[Dict[str, Any]] = None,
    ) -> int:
        """
        Remove BM25 docs that match a metadata_filter (in-memory only).

        This is used for versioned re-indexing (e.g. delete only a specific doc_pipeline_key),
        without dropping other versions that may still serve as the active pipeline.
        """
        if not metadata_filter or not isinstance(metadata_filter, dict):
            return 0

        tenant_key = self._tenant_key(tenant_id)
        existing = self._bm25_docs.get(tenant_key) or []
        if not existing:
            return 0

        before = len(existing)
        filtered = [d for d in existing if not self._match_metadata_filter((d.metadata or {}), metadata_filter)]
        removed = before - len(filtered)
        if removed <= 0:
            return 0

        retriever = BM25Retriever.from_documents(
            filtered,
            preprocess_func=self._bm25_tokenize,
            k=10,
        ) if filtered else None

        if retriever is None:
            self._bm25_retrievers.pop(tenant_key, None)
            self._bm25_docs.pop(tenant_key, None)
            self._bm25_doc_ids.pop(tenant_key, None)
            self._chunk_id_lookup.pop(tenant_key, None)
            self._bm25_build_locks.pop(tenant_key, None)
            with self._bm25_cache_lock:
                self._bm25_cache_order.pop(tenant_key, None)
            logger.info("BM25 index cleared for tenant %s after filtered deletion (removed=%s)", tenant_key, removed)
            return removed

        self._bm25_retrievers[tenant_key] = retriever
        self._bm25_docs[tenant_key] = filtered
        self._refresh_bm25_doc_ids(tenant_key, filtered)
        lookup: Dict[str, str] = {}
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
        self._chunk_id_lookup[tenant_key] = lookup
        self._touch_bm25_cache(tenant_key)
        logger.info("BM25 index removed %s docs by metadata_filter for tenant %s", removed, tenant_key)
        return removed

    def clear_bm25_cache(self) -> None:
        """Clear all cached BM25 indices (in-memory only)."""
        self._bm25_retrievers.clear()
        self._bm25_docs.clear()
        self._bm25_doc_ids.clear()
        self._chunk_id_lookup.clear()
        self._bm25_build_locks.clear()
        with self._bm25_cache_lock:
            self._bm25_cache_order.clear()

    def _search_bm25(
        self,
        query: str,
        top_k: int = 10,
        document_ids: Optional[List[UUID]] = None,
        tenant_id: Optional[UUID] = None,
        metadata_filter: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """BM25 keyword retrieval (internal use, returns dicts with scores)."""
        if not bool(getattr(settings, "BM25_INDEX_ENABLED", True)):
            return []
        tenant_key = self._tenant_key(tenant_id)
        retriever = self._bm25_retrievers.get(tenant_key)
        docs = self._bm25_docs.get(tenant_key)
        if retriever is None or docs is None:
            self._lazy_build_bm25_index(tenant_id=tenant_id, document_ids=document_ids)
            retriever = self._bm25_retrievers.get(tenant_key)
            docs = self._bm25_docs.get(tenant_key)
            if retriever is None or docs is None:
                logger.warning("BM25 index not initialized, skipping keyword search")
                return []

        self._touch_bm25_cache(tenant_key)

        allowed_ids = {str(doc_id) for doc_id in document_ids} if document_ids else None
        processed_query = retriever.preprocess_func(query)
        scores = retriever.vectorizer.get_scores(processed_query)  # type: ignore[attr-defined]

        results: List[Dict[str, Any]] = []
        for doc, score in zip(docs, scores, strict=False):
            meta = doc.metadata or {}
            if allowed_ids and str(meta.get("document_id")) not in allowed_ids:
                continue
            # Apply metadata filter if provided
            if metadata_filter and self.metadata_filter_enabled:
                if not self._match_metadata_filter(meta, metadata_filter):
                    continue
            results.append(
                {
                    "chunk_id": doc.id,
                    "content": doc.page_content,
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
                        "bm25_score": float(score),
                    },
                    "score": float(score),
                }
            )

        if not results:
            return []
        return heapq.nlargest(max(0, int(top_k or 0)), results, key=lambda x: float(x.get("score", 0.0) or 0.0))

    def _hybrid_search(
        self,
        query: str,
        top_k: int = 5,
        score_threshold: float = 0.7,
        document_ids: Optional[List[UUID]] = None,
        tenant_id: Optional[UUID] = None,
        alpha: float = 0.5,
        enable_weight_rerank: bool = True,
        vector_weight: float = 0.6,
        keyword_weight: float = 0.4,
        retrieval_mode: str = "hybrid",
        mmr_lambda: float = 0.7,
        mmr_fetch_k_multiplier: int = 4,
        metadata_filter: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Hybrid search: vector retrieval + BM25, optional reranking."""
        retrieval_mode = (retrieval_mode or "hybrid").lower()

        # Metadata filter strategy:
        # - BM25 sees Postgres chunk metadata (rich JSON) -> can apply most filters early.
        # - Milvus (document collection) stores a small fixed metadata schema -> only pass supported keys early
        #   to avoid false negatives when users filter on richer DB-only metadata.
        full_metadata_filter = metadata_filter if (metadata_filter and self.metadata_filter_enabled) else None
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
        bm25_filter: Optional[Dict[str, Any]] = None
        vector_filter: Optional[Dict[str, Any]] = None
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
            }
            vf: Dict[str, Any] = {}
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
            vector_filter = vf or None

        want_vector = retrieval_mode in ("hybrid", "vector", "mmr")
        want_bm25 = retrieval_mode in ("hybrid", "keyword", "mmr")
        if want_bm25 and not bool(getattr(settings, "BM25_INDEX_ENABLED", True)):
            # Enforce the global flag even if a BM25 cache exists; fall back to vector so "keyword"
            # mode doesn't become a hard-fail for users.
            want_bm25 = False
            if not want_vector:
                want_vector = True
                retrieval_mode = "vector"

        # MMR mode needs more candidates for diversity selection
        fetch_k = top_k * 2
        if retrieval_mode == "mmr":
            fetch_k = top_k * max(1, mmr_fetch_k_multiplier)

        # 1) Vector retrieval
        vector_results: List[Dict[str, Any]] = []
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

                vector_results = vector_store.search(**search_kwargs)
            except Exception as exc:
                logger.warning("Vector search failed: %s", exc)
                vector_results = []

        # 2) BM25 retrieval
        bm25_results: List[Dict[str, Any]] = []
        if want_bm25:
            bm25_results = self._search_bm25(
                query=query,
                top_k=fetch_k,
                document_ids=document_ids,
                tenant_id=tenant_id,
                metadata_filter=bm25_filter,
            )

        # Fallback: when single-channel mode fails, try the other channel.
        if retrieval_mode == "vector" and not vector_results:
            bm25_results = self._search_bm25(
                query=query,
                top_k=fetch_k,
                document_ids=document_ids,
                tenant_id=tenant_id,
                metadata_filter=bm25_filter,
            )
        elif retrieval_mode == "keyword" and not bm25_results:
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
                vector_results = vector_store.search(**fallback_kwargs)
            except Exception as exc:
                logger.warning("Vector search failed: %s", exc)
                vector_results = []

        # Defense-in-depth: if Milvus/Vector backend cannot push down a huge document_ids filter,
        # enforce the scope client-side to preserve semantics.
        if vector_results and document_ids:
            allowed = {str(did) for did in document_ids if did is not None}
            if allowed:
                filtered_vec: List[Dict[str, Any]] = []
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

        # 3) Score normalization + linear merge
        merged_results = self._merge_results(
            vector_results,
            bm25_results,
            alpha=alpha,
            fusion_strategy=self.fusion_strategy,
            rrf_k=self.rrf_k,
        )

        merged_results = self._deduplicate_results(merged_results)

        # 4) Reranking strategy
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
            provider = (self.reranker_provider or settings.RERANKER_PROVIDER or "llm").lower()
            if provider not in ("none", "off", "false", "0"):
                reranker = get_reranker(provider)
                candidates_n = int(self.reranker_top_n or settings.RERANKER_TOP_N or 20)
                candidates_n = max(candidates_n, top_k)
                candidates_n = min(candidates_n, len(merged_results))
                candidates: List[RerankCandidate] = []
                id_to_doc: Dict[str, Dict[str, Any]] = {}
                for doc in merged_results[:candidates_n]:
                    rid = self._result_key(doc)
                    text = (doc.get("content") or "").strip()
                    if not rid or not text:
                        continue
                    meta = dict(doc.get("metadata") or {})
                    meta["score"] = float(doc.get("score", 0.0) or 0.0)
                    candidates.append(RerankCandidate(id=rid, text=text, metadata=meta))
                    id_to_doc[rid] = doc

                if candidates:
                    try:
                        start = time.time()
                        result = reranker.rerank(
                            query=query,
                            candidates=candidates,
                            top_n=candidates_n,
                        )
                        rerank_elapsed = result.elapsed_sec or (time.time() - start)
                        rerank_provider = result.provider or provider

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
                        logger.warning("Reranker failed (%s): %s", provider, exc)
                        for doc in merged_results[:candidates_n]:
                            meta = dict(doc.get("metadata") or {})
                            meta.setdefault("reranker_provider", provider)
                            meta.setdefault("reranker_error", str(exc)[:200])
                            doc["metadata"] = meta

        merged_results = self._apply_document_diversity(merged_results, top_k=top_k)
        return merged_results[:top_k]

    # ---- LangChain Retriever API ----

    def _enrich_results_with_db_metadata(
        self,
        results: List[Dict[str, Any]],
        *,
        stats: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Vector store may return "trimmed" metadata (e.g., without img_id).
        Use chunk_id / (document_id, chunk_index) to look up DB and fill in key fields:
        - img_id: For MinIO image display
        - page/source: For context annotation (keeping consistent with DB)
        """
        if not results:
            return results

        if stats is not None:
            stats.clear()
            stats["input_results"] = len(results)
            stats["filtered_orphaned"] = 0
            stats["filtered_acl"] = 0
            stats["filtered_dataset"] = 0
            stats["filtered_not_ready"] = 0
            stats["filtered_embedding_space"] = 0
            stats["filtered_pipeline_version"] = 0
            stats["filtered_metadata_filter"] = 0
            stats["output_results"] = 0
            stats["exception"] = None

        db = SessionLocal()
        try:
            tenant_filter = self.tenant_id
            account_id = (self.account_id or "").strip() or None
            dataset_filter = self.dataset_id
            embedding_space = current_embedding_space_hash()

            chunk_ids: List[UUID] = []
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
                except Exception:
                    continue

            chunks_by_id: Dict[str, DocumentChunk] = {}
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
                except Exception:
                    continue
                missing_pairs.add((doc_uuid, chunk_idx))

            chunks_by_pair: Dict[tuple[str, int], DocumentChunk] = {}
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
            doc_user_by_id: Dict[str, Dict[str, Any]] = {}
            doc_dataset_by_id: Dict[str, str] = {}
            doc_ready_by_id: Dict[str, bool] = {}
            doc_active_pipeline_key_by_id: Dict[str, str] = {}
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
                    ).filter(DBDocument.id.in_(sorted(doc_ids)))
                    if tenant_filter:
                        dq = dq.filter(DBDocument.tenant_id == tenant_filter)
                    for doc_id, ds_id, status, doc_meta, archived_at, disabled_at in dq.all():
                        meta0 = doc_meta if isinstance(doc_meta, dict) else {}
                        user0 = meta0.get("user") if isinstance(meta0.get("user"), dict) else {}
                        if user0:
                            doc_user_by_id[str(doc_id)] = dict(user0)
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
                        doc_ready_by_id[str(doc_id)] = bool(ready)

                        active_key = str(meta0.get("active_doc_pipeline_key") or "").strip()
                        if not active_key:
                            active_hash = str(meta0.get("active_pipeline_hash") or meta0.get("pipeline_hash") or "").strip()
                            if active_hash:
                                active_key = f"{doc_id}:{active_hash}"
                        if ready and active_key:
                            doc_active_pipeline_key_by_id[str(doc_id)] = active_key
            except Exception:
                doc_user_by_id = {}
                doc_dataset_by_id = {}
                doc_ready_by_id = {}
                doc_active_pipeline_key_by_id = {}

            # Candidate-level ACL trimming (security trimming) and dataset scoping.
            # This enables "open scope" retrieval (no precomputed allowed_doc_ids list) without leaking data.
            allowed_docs_str: Optional[set[str]] = None
            if tenant_filter and account_id:
                try:
                    from app.services.document_access import get_allowed_document_id_sets

                    candidate_doc_ids: set[UUID] = set()
                    for k in doc_ready_by_id.keys():
                        if not k:
                            continue
                        try:
                            candidate_doc_ids.add(UUID(str(k)))
                        except Exception:
                            continue
                    # Reduce work: if we cannot prove a doc is "ready", treat it as non-searchable.
                    ready_doc_ids: set[UUID] = set()
                    for doc_id, ok in doc_ready_by_id.items():
                        if not ok:
                            continue
                        try:
                            ready_doc_ids.add(UUID(str(doc_id)))
                        except Exception:
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
                except Exception:
                    # Fail closed: if ACL check fails, do not return potentially sensitive chunks.
                    allowed_docs_str = set()
            elif account_id and not tenant_filter:
                # If caller provided account_id but not tenant_id, fail closed.
                allowed_docs_str = set()

            resolved: List[Dict[str, Any]] = []
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
                    except Exception:
                        doc_uuid = None
                        chunk_idx = None
                    if doc_uuid is not None and chunk_idx is not None:
                        ck = chunks_by_pair.get((str(doc_uuid), chunk_idx))

                # If we know tenant_id, treat unresolved results as stale (e.g. orphan vectors).
                if ck is None and tenant_filter:
                    if stats is not None:
                        stats["filtered_orphaned"] = int(stats.get("filtered_orphaned", 0) or 0) + 1
                    continue

                if ck is not None:
                    # Enforce candidate-level dataset/ACL trimming once we know the resolved document_id.
                    doc_id_str = str(ck.document_id)
                    if allowed_docs_str is not None and doc_id_str not in allowed_docs_str:
                        if stats is not None:
                            stats["filtered_acl"] = int(stats.get("filtered_acl", 0) or 0) + 1
                        continue
                    if dataset_filter is not None:
                        want = str(dataset_filter)
                        if doc_dataset_by_id.get(doc_id_str) != want:
                            if stats is not None:
                                stats["filtered_dataset"] = int(stats.get("filtered_dataset", 0) or 0) + 1
                            continue
                    if getattr(ck, "disabled_at", None) is not None:
                        if stats is not None:
                            stats["filtered_not_ready"] = int(stats.get("filtered_not_ready", 0) or 0) + 1
                        continue
                    if doc_ready_by_id and not doc_ready_by_id.get(doc_id_str, False):
                        if stats is not None:
                            stats["filtered_not_ready"] = int(stats.get("filtered_not_ready", 0) or 0) + 1
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
                    except Exception:
                        pass

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
                        except Exception:
                            pass
                    if stored_meta.get("parser_backend") and not meta.get("parser_backend"):
                        meta["parser_backend"] = stored_meta.get("parser_backend")
                    if stored_meta.get("doc_type_kwd") and not meta.get("doc_type_kwd"):
                        meta["doc_type_kwd"] = stored_meta.get("doc_type_kwd")
                    for key in ("header_path", "header_context", "chunk_strategy", "chunk_role", "parent_id"):
                        if stored_meta.get(key) and not meta.get(key):
                            meta[key] = stored_meta.get(key)

                    # Attach document-level user metadata for metadata filtering / enterprise search facets.
                    doc_user = doc_user_by_id.get(str(ck.document_id))
                    if doc_user and not meta.get("document_user"):
                        meta["document_user"] = doc_user

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
                            if stats is not None:
                                stats["filtered_embedding_space"] = (
                                    int(stats.get("filtered_embedding_space", 0) or 0) + 1
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
                            if stats is not None:
                                stats["filtered_pipeline_version"] = (
                                    int(stats.get("filtered_pipeline_version", 0) or 0) + 1
                                )
                            continue

                r["metadata"] = meta
                resolved.append(r)

            # Apply the full metadata filter *after* DB enrichment.
            if self.metadata_filter and self.metadata_filter_enabled:
                try:
                    before = len(resolved)
                    filtered: List[Dict[str, Any]] = []
                    for item in resolved:
                        m = item.get("metadata") or {}
                        if isinstance(m, dict) and self._match_metadata_filter(m, self.metadata_filter):
                            filtered.append(item)
                    resolved = filtered
                    if stats is not None:
                        stats["filtered_metadata_filter"] = max(0, before - len(resolved))
                except Exception:
                    pass

            if stats is not None:
                stats["output_results"] = len(resolved)
            return resolved
        except Exception as exc:
            if stats is not None:
                stats["exception"] = str(exc)[:200]
            return results
        finally:
            try:
                db.close()
            except Exception:
                pass

    def _expand_results_with_neighbors(self, results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Optionally attach adjacent chunks around top hits for better continuity."""
        if not results:
            return results

        window = max(0, int(getattr(settings, "RAG_CONTEXT_NEIGHBOR_WINDOW", 0) or 0))
        if window <= 0:
            return results

        max_added = max(0, int(getattr(settings, "RAG_CONTEXT_NEIGHBOR_MAX_ADDED", 0) or 0))
        tenant_filter = self.tenant_id

        # Version-aware neighbor fetch:
        # - Some installations keep multiple pipeline versions in `document_chunks`.
        # - We must avoid pulling neighbors from an inactive pipeline version, even for the same document.
        desired_pipeline_by_doc: dict[str, str] = {}

        anchors: list[tuple[Dict[str, Any], UUID | None, int | None, str | None]] = []
        for r in results:
            meta = r.get("metadata") or {}
            doc_id = meta.get("document_id")
            chunk_index = meta.get("chunk_index")
            try:
                doc_uuid = UUID(str(doc_id)) if doc_id is not None else None
                idx = int(chunk_index) if chunk_index is not None else None
            except Exception:
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

        needed_pairs: set[tuple[UUID, int]] = set()
        for _, doc_uuid, idx, _pk in anchors:
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
        except Exception:
            return results
        finally:
            try:
                db.close()
            except Exception:
                pass

        seen: set[str] = set()
        for r in results:
            cid = r.get("chunk_id") or (r.get("metadata") or {}).get("chunk_id")
            if cid:
                seen.add(str(cid))

        expanded: list[Dict[str, Any]] = []
        added_neighbors = 0
        for r, doc_uuid, idx, _pk in anchors:
            meta = r.get("metadata") or {}
            anchor_cid = str(r.get("chunk_id") or meta.get("chunk_id") or "")

            # Build a [prev..anchor..next] group in document order.
            if doc_uuid is not None and idx is not None:
                doc_key = str(doc_uuid)
                for gi in range(idx - window, idx + window + 1):
                    if gi < 0:
                        continue
                    if gi == idx:
                        if anchor_cid and anchor_cid not in seen:
                            seen.add(anchor_cid)
                        expanded.append(r)
                        continue

                    ck = neighbors_by_pair.get((doc_key, gi))
                    if ck is None:
                        continue
                    ck_id = str(ck.id)
                    if ck_id in seen:
                        continue
                    if max_added and added_neighbors >= max_added:
                        continue

                    stored_meta = dict(ck.doc_metadata or {})
                    stored_meta.setdefault("tenant_id", str(ck.tenant_id))
                    stored_meta.setdefault("document_id", str(ck.document_id))
                    stored_meta.setdefault("chunk_index", int(ck.chunk_index))
                    stored_meta.setdefault("chunk_id", ck_id)
                    if ck.page_number is not None:
                        stored_meta.setdefault("page", ck.page_number)
                    if not stored_meta.get("source"):
                        stored_meta["source"] = "unknown"
                    stored_meta["neighbor_of"] = anchor_cid
                    stored_meta["retrieval_role"] = "neighbor"

                    anchor_score = float(r.get("score", 0.0) or 0.0)
                    neighbor_score = float(anchor_score * 0.85) if anchor_score else 0.0
                    expanded.append(
                        {
                            "chunk_id": ck_id,
                            "content": ck.content,
                            "metadata": stored_meta,
                            "score": neighbor_score,
                        }
                    )
                    seen.add(ck_id)
                    added_neighbors += 1
            else:
                expanded.append(r)

        return expanded

    def _auto_merge_parent_child(self, results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
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

        # Group child hits by (document_id, parent_id).
        child_groups: dict[tuple[str, str], list[Dict[str, Any]]] = {}
        parent_results: dict[tuple[str, str], Dict[str, Any]] = {}

        # For neighbor cleanup (replace mode).
        child_chunk_ids_by_group: dict[tuple[str, str], set[str]] = {}

        for r in results:
            meta = r.get("metadata") or {}
            role = str(meta.get("chunk_role") or "").strip().lower()
            parent_id = str(meta.get("parent_id") or meta.get("parent_node_id") or "").strip()
            doc_id = str(meta.get("document_id") or "").strip()
            if not parent_id or not doc_id:
                continue

            cid = r.get("chunk_id") or meta.get("chunk_id")
            cid_str = str(cid) if cid else ""

            if role == "parent":
                parent_results[(doc_id, parent_id)] = r
            elif role == "child":
                key = (doc_id, parent_id)
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
                except Exception:
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
            parent_ids: set[str] = set()
            for doc_id, parent_id in missing_keys:
                try:
                    doc_ids.add(UUID(doc_id))
                except Exception:
                    continue
                if parent_id:
                    parent_ids.add(parent_id)

            if doc_ids and parent_ids:
                db = SessionLocal()
                try:
                    q = db.query(DocumentChunk).filter(DocumentChunk.document_id.in_(list(doc_ids)))
                    if tenant_filter:
                        q = q.filter(DocumentChunk.tenant_id == tenant_filter)
                    # JSONB lookup: metadata->>'chunk_role' == 'parent' and metadata->>'parent_id' in (...)
                    q = q.filter(DocumentChunk.doc_metadata["chunk_role"].astext == "parent")  # type: ignore[attr-defined]
                    q = q.filter(DocumentChunk.doc_metadata["parent_id"].astext.in_(list(parent_ids)))  # type: ignore[attr-defined]
                    for ck in q.all():
                        meta = dict(getattr(ck, "doc_metadata", None) or {})
                        pid = str(meta.get("parent_id") or "").strip()
                        if not pid:
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
                        fetched_parents[(str(ck.document_id), pid)] = ck
                except Exception:
                    fetched_parents = {}
                finally:
                    try:
                        db.close()
                    except Exception:
                        pass

        # Helper: materialize a parent result dict.
        def _parent_result_for(key: tuple[str, str], *, best_child_score: float) -> Dict[str, Any] | None:
            if key in parent_results:
                # If parent is already present (e.g., neighbor expansion), bump its score and mark role.
                existing = parent_results[key]
                meta = dict(existing.get("metadata") or {})
                meta["retrieval_role"] = "parent"
                existing["metadata"] = meta
                try:
                    existing_score = float(existing.get("score", 0.0) or 0.0)
                except Exception:
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
                except Exception:
                    continue
            best_score_by_group[key] = best

        if mode == "append":
            inserted: set[tuple[str, str]] = set()
            out: list[Dict[str, Any]] = []
            for r in results:
                out.append(r)
                meta = r.get("metadata") or {}
                role = str(meta.get("chunk_role") or "").strip().lower()
                if role != "child":
                    continue
                key = (str(meta.get("document_id") or "").strip(), str(meta.get("parent_id") or meta.get("parent_node_id") or "").strip())
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
        out: list[Dict[str, Any]] = []
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
                str(meta.get("parent_id") or meta.get("parent_node_id") or "").strip(),
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
    ) -> List[Document]:
        requested_k = max(1, int(self.k or 0))
        # When running in open scope (no explicit document_ids), we may drop candidates due to:
        # - document/dataset ACL (security trimming)
        # - active pipeline version trimming
        # Over-fetch to keep enough final results after trimming.
        search_k = requested_k
        if self.tenant_id and (self.account_id or "").strip() and not (self.document_ids or []):
            mult = max(1, int(getattr(settings, "RETRIEVAL_OVERFETCH_MULTIPLIER", 1) or 1))
            if mult > 1:
                search_k = max(search_k, requested_k * mult)
                cap = int(getattr(settings, "RETRIEVAL_OVERFETCH_MAX_K", 0) or 0)
                if cap > 0:
                    search_k = min(search_k, cap)

        debug: Dict[str, Any] = {
            "requested_k": int(requested_k),
            "search_k": int(search_k),
            "overfetch_enabled": bool(search_k > requested_k),
            "overfetch_multiplier": int(getattr(settings, "RETRIEVAL_OVERFETCH_MULTIPLIER", 1) or 1),
            "overfetch_cap_k": int(getattr(settings, "RETRIEVAL_OVERFETCH_MAX_K", 0) or 0),
            "scope": {
                "tenant_id": str(self.tenant_id or ""),
                "account_id_present": bool((self.account_id or "").strip()),
                "dataset_id": str(self.dataset_id or ""),
                "document_ids_count": len(self.document_ids or []),
                "kind": (
                    "document_ids"
                    if (self.document_ids or [])
                    else ("dataset_id" if self.dataset_id is not None else "open")
                ),
            },
        }
        try:
            max_doc_ids = int(getattr(settings, "MILVUS_EXPR_MAX_DOC_IDS", 0) or 0)
            debug["milvus_doc_id_pushdown_skipped"] = bool(
                settings.VECTOR_BACKEND == "milvus"
                and max_doc_ids > 0
                and self.document_ids
                and len(self.document_ids) > max_doc_ids
            )
            debug["milvus_expr_max_doc_ids"] = int(max_doc_ids)
        except Exception:
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
            metadata_filter=self.metadata_filter,
        )
        debug["hybrid_results"] = len(results or [])
        enrich1: Dict[str, Any] = {}
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
        enrich2: Dict[str, Any] = {}
        results = self._enrich_results_with_db_metadata(results, stats=enrich2)
        debug["enrich_pass2"] = enrich2
        debug["final_results"] = len(results or [])
        docs: List[Document] = []
        for r in results:
            meta = dict(r.get("metadata") or {})
            meta["score"] = r.get("score")
            meta["vector_score"] = r.get("vector_score")
            meta["bm25_score"] = r.get("bm25_score")
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
        return docs[:requested_k]

    async def _aget_relevant_documents(
        self,
        query: str,
        *,
        run_manager: AsyncCallbackManagerForRetrieverRun,
    ) -> List[Document]:
        return self._get_relevant_documents(query, run_manager=CallbackManagerForRetrieverRun.get_noop_manager())

    def _result_key(self, result: Dict[str, Any]) -> str:
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

    def _get_doc_id(self, result: Dict[str, Any]) -> str:
        meta = result.get("metadata") or {}
        doc_id = meta.get("document_id")
        return str(doc_id) if doc_id is not None else ""

    def _match_metadata_filter(self, meta: Dict[str, Any], filter_spec: Dict[str, Any]) -> bool:
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

    def _deduplicate_results(self, results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not results or not bool(self.dedup_enabled):
            return results

        threshold = float(self.dedup_jaccard_threshold or 0.0)
        threshold = max(0.0, min(threshold, 1.0))
        max_compare = int(self.dedup_max_compare or 0)
        max_compare = max(0, max_compare)

        seen_chunk_ids: set[str] = set()
        seen_fingerprints: set[str] = set()
        kept: List[Dict[str, Any]] = []
        kept_tokens_by_doc: Dict[str, List[set[str]]] = {}

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

            fp = self._fingerprint(content)
            if fp in seen_fingerprints:
                continue
            seen_fingerprints.add(fp)

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

        return kept

    def _apply_document_diversity(self, results: List[Dict[str, Any]], *, top_k: int) -> List[Dict[str, Any]]:
        if not results:
            return results

        max_per_doc = int(self.max_chunks_per_doc or 0)
        min_docs = int(self.min_distinct_docs or 0)
        if max_per_doc <= 0 and min_docs <= 0:
            return results

        groups: Dict[str, List[Dict[str, Any]]] = {}
        for r in results:
            groups.setdefault(self._get_doc_id(r), []).append(r)

        must_have: List[Dict[str, Any]] = []
        if min_docs > 0:
            firsts = [items[0] for items in groups.values() if items]
            firsts.sort(key=lambda x: float(x.get("score", 0.0) or 0.0), reverse=True)
            must_have = firsts[: max(0, min(min_docs, len(firsts), top_k))]

        selected: List[Dict[str, Any]] = []
        used_keys: set[str] = set()
        per_doc = Counter()
        for r in must_have:
            k = self._result_key(r)
            if k in used_keys:
                continue
            used_keys.add(k)
            selected.append(r)
            per_doc[self._get_doc_id(r)] += 1

        overflow: List[Dict[str, Any]] = []
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
            used_keys.add(k)
            selected.append(r)
            per_doc[doc_id] += 1

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
            return selected

        rest = [r for r in results if self._result_key(r) not in used_keys]
        return selected + rest

    def _merge_results(
        self,
        vector_results: List[Dict[str, Any]],
        bm25_results: List[Dict[str, Any]],
        alpha: float = 0.5,
        fusion_strategy: str | None = None,
        rrf_k: int | None = None,
    ) -> List[Dict[str, Any]]:
        """Merge vector/BM25 results into a single ranked list."""

        def normalize(results: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
            if not results:
                return {}
            scores = [r.get("score", 0.0) for r in results]
            min_score = min(scores)
            max_score = max(scores)
            rng = max_score - min_score if max_score > min_score else 1.0
            out: Dict[str, Dict[str, Any]] = {}
            for r in results:
                key = self._result_key(r)
                out[key] = {
                    "score": (r.get("score", 0.0) - min_score) / rng,
                    "data": r,
                }
            return out

        vector_norm = normalize(vector_results)
        bm25_norm = normalize(bm25_results)

        fusion = (fusion_strategy or "linear").lower().strip()
        if fusion in ("rrf", "reciprocal_rank_fusion"):
            v_sorted = sorted(vector_results, key=lambda x: float(x.get("score", 0.0) or 0.0), reverse=True)
            b_sorted = sorted(bm25_results, key=lambda x: float(x.get("score", 0.0) or 0.0), reverse=True)

            v_rank: Dict[str, int] = {}
            b_rank: Dict[str, int] = {}
            for idx, r in enumerate(v_sorted, 1):
                key = self._result_key(r)
                if key not in v_rank:
                    v_rank[key] = idx
            for idx, r in enumerate(b_sorted, 1):
                key = self._result_key(r)
                if key not in b_rank:
                    b_rank[key] = idx

            k0 = int(rrf_k or 0) or int(getattr(self, "rrf_k", 60) or 60)
            k0 = max(1, k0)

            merged: Dict[str, Dict[str, Any]] = {}
            raw_scores: List[float] = []
            for key in set(vector_norm.keys()) | set(bm25_norm.keys()):
                v_data = vector_norm.get(key, {}).get("data")
                b_data = bm25_norm.get(key, {}).get("data")
                data = v_data or b_data
                if not data:
                    continue

                if v_data and b_data:
                    merged_meta = dict(v_data.get("metadata") or {})
                    b_meta = b_data.get("metadata") or {}
                    for mk, mv in b_meta.items():
                        if mk not in merged_meta or merged_meta.get(mk) in (None, "", [], {}):
                            merged_meta[mk] = mv
                    merged_data = dict(v_data)
                    merged_data["metadata"] = merged_meta
                    if not merged_data.get("chunk_id") and b_data.get("chunk_id"):
                        merged_data["chunk_id"] = b_data.get("chunk_id")
                    data = merged_data

                vr = v_rank.get(key)
                br = b_rank.get(key)
                rrf_raw = (1.0 / (k0 + vr)) if vr else 0.0
                rrf_raw += (1.0 / (k0 + br)) if br else 0.0
                raw_scores.append(float(rrf_raw))

                merged[key] = {
                    **data,
                    "vector_score": float(vector_norm.get(key, {}).get("score", 0.0) or 0.0),
                    "bm25_score": float(bm25_norm.get(key, {}).get("score", 0.0) or 0.0),
                    "rrf_score_raw": float(rrf_raw),
                    "rrf_k": k0,
                    "rrf_rank_vector": vr,
                    "rrf_rank_bm25": br,
                    "fusion_strategy": "rrf",
                    "score": float(rrf_raw),
                }

            if merged:
                min_s = min(raw_scores) if raw_scores else 0.0
                max_s = max(raw_scores) if raw_scores else 0.0
                rng = max_s - min_s if max_s > min_s else 1.0
                for item in merged.values():
                    raw = float(item.get("rrf_score_raw", 0.0) or 0.0)
                    item["score"] = (raw - min_s) / rng

            return sorted(merged.values(), key=lambda x: float(x.get("score", 0.0) or 0.0), reverse=True)

        merged: Dict[str, Dict[str, Any]] = {}
        for key in set(vector_norm.keys()) | set(bm25_norm.keys()):
            v_score = vector_norm.get(key, {}).get("score", 0.0)
            b_score = bm25_norm.get(key, {}).get("score", 0.0)
            v_data = vector_norm.get(key, {}).get("data")
            b_data = bm25_norm.get(key, {}).get("data")
            data = v_data or b_data
            if not data:
                continue

            # Merge metadata from both channels (e.g., img_id may only exist in BM25/DB metadata)
            if v_data and b_data:
                merged_meta = dict(v_data.get("metadata") or {})
                b_meta = b_data.get("metadata") or {}
                for k, v in b_meta.items():
                    if k not in merged_meta or merged_meta.get(k) in (None, "", [], {}):
                        merged_meta[k] = v
                merged_data = dict(v_data)
                merged_data["metadata"] = merged_meta
                if not merged_data.get("chunk_id") and b_data.get("chunk_id"):
                    merged_data["chunk_id"] = b_data.get("chunk_id")
                data = merged_data

            has_v = key in vector_norm
            has_b = key in bm25_norm
            if has_v and has_b:
                fused_score = alpha * float(v_score) + (1 - alpha) * float(b_score)
            elif has_v:
                fused_score = float(v_score)
            else:
                fused_score = float(b_score)

            merged[key] = {
                **data,
                "vector_score": float(v_score),
                "bm25_score": float(b_score),
                "fusion_strategy": "linear",
                "score": fused_score,
            }

        return sorted(merged.values(), key=lambda x: float(x.get("score", 0.0) or 0.0), reverse=True)

    def _weight_rerank(
        self,
        query: str,
        documents: List[Dict[str, Any]],
        vector_weight: float = 0.6,
        keyword_weight: float = 0.4,
    ) -> List[Dict[str, Any]]:
        """Vector score + keyword TF-IDF cosine linear weighting."""
        if not documents:
            return documents

        query_tokens = self._bm25_tokenize(query)
        doc_tokens_list = [self._bm25_tokenize(doc.get("content", "")) for doc in documents]

        all_tokens = set(tok for tokens in doc_tokens_list for tok in tokens)
        if not all_tokens:
            return documents

        doc_count = len(documents)
        token_idf: Dict[str, float] = {}
        for tok in all_tokens:
            df = sum(1 for tokens in doc_tokens_list if tok in tokens)
            token_idf[tok] = math.log((1 + doc_count) / (1 + df)) + 1

        def tfidf_vec(tokens: List[str]) -> Dict[str, float]:
            tf = Counter(tokens)
            return {t: tf[t] * token_idf.get(t, 0.0) for t in tf}

        query_vec = tfidf_vec(query_tokens)
        doc_vecs = [tfidf_vec(tokens) for tokens in doc_tokens_list]

        def cosine(a: Dict[str, float], b: Dict[str, float]) -> float:
            if not a or not b:
                return 0.0
            common = set(a.keys()) & set(b.keys())
            num = sum(a[t] * b[t] for t in common)
            denom = math.sqrt(sum(v * v for v in a.values())) * math.sqrt(sum(v * v for v in b.values()))
            return num / denom if denom else 0.0

        keyword_scores = [cosine(query_vec, v) for v in doc_vecs]

        reranked: List[Dict[str, Any]] = []
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
        documents: List[Dict[str, Any]],
        query: str,
        top_k: int,
        lambda_mult: float = 0.7,
    ) -> List[Dict[str, Any]]:
        """
        Simple MMR (Maximal Marginal Relevance) reranking:
        max lambda*sim(query, doc) - (1-lambda)*max sim(doc, selected)
        Uses bag-of-words Jaccard approximation, lightweight with no extra dependencies.
        """
        if not documents:
            return documents

        lambda_mult = max(min(lambda_mult, 1.0), 0.0)
        selected: List[Dict[str, Any]] = []
        candidates = list(documents)
        # Pre-cache tokens to avoid multiple tokenizations
        tokens_map = {id(doc): self._tokenize_for_similarity(doc.get("content", "")) for doc in candidates}

        def doc_similarity(doc_a: Dict[str, Any], doc_b: Dict[str, Any]) -> float:
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

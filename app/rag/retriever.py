"""
Hybrid Retriever: Vector retrieval + BM25 + optional MMR diversity reranking.
Reference: RAG_Agent example repository. Retrieval modes and reranking strategies are configurable.
"""
from __future__ import annotations

from typing import List, Dict, Any, Optional
from uuid import UUID
import math
import re
from collections import Counter
import heapq
import jieba
import time
import threading

from langchain_core.documents import Document
from langchain_core.callbacks import CallbackManagerForRetrieverRun, AsyncCallbackManagerForRetrieverRun
from langchain_core.retrievers import BaseRetriever
from langchain_community.retrievers.bm25 import BM25Retriever
from pydantic import PrivateAttr, ConfigDict
from sqlalchemy import tuple_
from sqlalchemy.orm import Session

from app.storage.vector.factory import get_vector_store
from app.models.document import DocumentChunk, Document as DBDocument
from app.core.config import settings
from app.core.database import SessionLocal
from app.rag.core.filters import match_metadata_filter
from app.rag.reranker.factory import get_reranker
from app.rag.reranker.types import RerankCandidate
from app.rag.core.logging import get_logger
from app.rag.preprocessing.stopwords import STOPWORDS
from app.rag.preprocessing.tokenization import tokenize_for_bm25


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
                    return True
            else:
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
                        return True
                else:
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
            chunk_index = meta.get("chunk_index")
            if doc_id is None or chunk_index is None or d.id is None:
                continue
            lookup[f"{doc_id}:{chunk_index}"] = str(d.id)
        self._chunk_id_lookup[tenant_key] = lookup
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
            chunk_index = meta.get("chunk_index")
            if doc_id is None or chunk_index is None or d.id is None:
                continue
            lookup[f"{doc_id}:{chunk_index}"] = str(d.id)
        self._chunk_id_lookup[tenant_key] = lookup
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
            logger.info("BM25 index cleared for tenant %s", tenant_key)
            return
        self._bm25_retrievers[tenant_key] = retriever
        self._bm25_docs[tenant_key] = filtered
        self._refresh_bm25_doc_ids(tenant_key, filtered)
        lookup: Dict[str, str] = {}
        for d in filtered:
            meta = d.metadata or {}
            doc_id = meta.get("document_id")
            chunk_index = meta.get("chunk_index")
            if doc_id is None or chunk_index is None or d.id is None:
                continue
            lookup[f"{doc_id}:{chunk_index}"] = str(d.id)
        self._chunk_id_lookup[tenant_key] = lookup
        logger.info("BM25 index removed document %s for tenant %s", document_id, tenant_key)

    def _search_bm25(
        self,
        query: str,
        top_k: int = 10,
        document_ids: Optional[List[UUID]] = None,
        tenant_id: Optional[UUID] = None,
        metadata_filter: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """BM25 keyword retrieval (internal use, returns dicts with scores)."""
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

        allowed_ids = {str(doc_id) for doc_id in document_ids} if document_ids else None
        processed_query = retriever.preprocess_func(query)
        scores = retriever.vectorizer.get_scores(processed_query)  # type: ignore[attr-defined]

        results: List[Dict[str, Any]] = []
        for doc, score in zip(docs, scores):
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

        want_vector = retrieval_mode in ("hybrid", "vector", "mmr")
        want_bm25 = retrieval_mode in ("hybrid", "keyword", "mmr")

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
                if metadata_filter and self.metadata_filter_enabled:
                    search_kwargs["metadata_filter"] = metadata_filter

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
                metadata_filter=metadata_filter,
            )

        # Fallback: when single-channel mode fails, try the other channel.
        if retrieval_mode == "vector" and not vector_results:
            bm25_results = self._search_bm25(
                query=query,
                top_k=fetch_k,
                document_ids=document_ids,
                tenant_id=tenant_id,
                metadata_filter=metadata_filter,
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
                if metadata_filter and self.metadata_filter_enabled:
                    fallback_kwargs["metadata_filter"] = metadata_filter
                vector_results = vector_store.search(**fallback_kwargs)
            except Exception as exc:
                logger.warning("Vector search failed: %s", exc)
                vector_results = []

        # Try to fill in chunk_id for vector retrieval results (for citations / RAGAS contexts)
        if vector_results:
            if metadata_filter and self.metadata_filter_enabled:
                vector_results = [
                    r for r in vector_results if self._match_metadata_filter((r.get("metadata") or {}), metadata_filter)
                ]
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
                key = f"{doc_id}:{chunk_index}"
                mapped = lookup.get(key)
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

    def _enrich_results_with_db_metadata(self, results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Vector store may return "trimmed" metadata (e.g., without img_id).
        Use chunk_id / (document_id, chunk_index) to look up DB and fill in key fields:
        - img_id: For MinIO image display
        - page/source: For context annotation (keeping consistent with DB)
        """
        if not results:
            return results

        db = SessionLocal()
        try:
            tenant_filter = self.tenant_id

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
                    continue

                if ck is not None:
                    cid_str = str(ck.id)
                    r["chunk_id"] = cid_str
                    meta["chunk_id"] = cid_str
                    chunks_by_id[cid_str] = ck

                    # Merge DB metadata (only fill empty fields, avoid overwriting vector-side score etc.)
                    stored_meta = dict(ck.doc_metadata or {})
                    if stored_meta.get("img_id") and not meta.get("img_id"):
                        meta["img_id"] = stored_meta.get("img_id")
                    if stored_meta.get("source") and not meta.get("source"):
                        meta["source"] = stored_meta.get("source")
                    if (ck.page_number is not None) and not meta.get("page"):
                        meta["page"] = ck.page_number
                    if stored_meta.get("parser_backend") and not meta.get("parser_backend"):
                        meta["parser_backend"] = stored_meta.get("parser_backend")
                    if stored_meta.get("doc_type_kwd") and not meta.get("doc_type_kwd"):
                        meta["doc_type_kwd"] = stored_meta.get("doc_type_kwd")
                    for key in ("header_path", "header_context", "chunk_strategy", "chunk_role", "parent_id"):
                        if stored_meta.get(key) and not meta.get(key):
                            meta[key] = stored_meta.get(key)

                r["metadata"] = meta
                resolved.append(r)

            return resolved
        except Exception:
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

        anchors: list[tuple[Dict[str, Any], UUID | None, int | None]] = []
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
            anchors.append((r, doc_uuid, idx))

        needed_pairs: set[tuple[UUID, int]] = set()
        for _, doc_uuid, idx in anchors:
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
                neighbors_by_pair[(str(ck.document_id), int(ck.chunk_index))] = ck
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
        for r, doc_uuid, idx in anchors:
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

    def _get_relevant_documents(
        self,
        query: str,
        *,
        run_manager: CallbackManagerForRetrieverRun,
    ) -> List[Document]:
        results = self._hybrid_search(
            query=query,
            top_k=self.k,
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
        results = self._enrich_results_with_db_metadata(results)
        results = self._expand_results_with_neighbors(results)
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
        return docs

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
        return str(result.get("chunk_id") or chunk_index or hash(result.get("content", "")))

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

            # 合并两路 metadata（例如 img_id 可能只存在于 BM25/DB metadata）
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
        for doc, kw_score in zip(documents, keyword_scores):
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

"""BM25 index lifecycle for the hybrid retriever.

Split out of ``app.rag.retriever`` (see ``app.rag.retrieval.hybrid``): scope
cache management, lazy/incremental builds, rebuilds from DB, upsert/removal,
and the BM25 search channel. Methods run on the ``HybridRetriever`` instance
via mixin inheritance; sessions are opened via ``self._open_session()`` so
monkeypatches on ``app.rag.retriever.SessionLocal`` keep working.
"""

import threading
from typing import Any
from uuid import UUID

from langchain_community.retrievers.bm25 import BM25Retriever
from langchain_core.documents import Document
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.dataset import Dataset as DBDataset
from app.models.document import Document as DBDocument
from app.models.document import DocumentChunk
from app.rag.core.hashing import stable_hash
from app.rag.preprocessing.tokenization import tokenize_for_bm25
from app.rag.retrieval.hybrid.common import (
    _PIPELINE_PLUGIN_METADATA_KEYS,
    _PLATFORM_METADATA_VIEW_KEYS,
    NON_CRITICAL_RETRIEVER_FALLBACK_LOG,
    _log_retriever_fallback,
    logger,
)


class Bm25IndexMixin:
    """BM25 scope caches, builds, upserts, removals, and keyword search."""

    def _refresh_bm25_doc_ids(self, tenant_key: str, docs: list[Document] | None) -> None:
        doc_ids: set[str] = set()
        for d in docs or []:
            meta = d.metadata or {}
            doc_id = meta.get("document_id")
            if doc_id is None:
                continue
            s = str(doc_id).strip()
            if s:
                doc_ids.add(s)
        with self._bm25_cache_lock:
            if docs:
                self._bm25_doc_ids[tenant_key] = doc_ids
            else:
                self._bm25_doc_ids.pop(tenant_key, None)

    @staticmethod
    def _query_maybe_call(query: Any, method_name: str, *args: Any, **kwargs: Any) -> Any:
        method = getattr(query, method_name, None)
        if not callable(method):
            return query
        try:
            return method(*args, **kwargs)
        except TypeError:
            return query

    @staticmethod
    def _iter_query_rows(query: Any, batch_size: int = 2000) -> Any:
        yield_per = getattr(query, "yield_per", None)
        if callable(yield_per):
            try:
                return yield_per(batch_size)
            except TypeError as exc:
                logger.debug(NON_CRITICAL_RETRIEVER_FALLBACK_LOG, exc)
        all_rows = getattr(query, "all", None)
        if callable(all_rows):
            return all_rows()
        return []

    @staticmethod
    def _unpack_chunk_row(row: Any) -> tuple[Any, Any, Any, Any, Any, Any, Any, Any]:
        try:
            (
                chunk_id,
                content,
                doc_metadata,
                tenant_uuid_row,
                document_uuid_row,
                chunk_index,
                page_number,
                dataset_uuid_row,
            ) = row
            return (
                chunk_id,
                content,
                doc_metadata,
                tenant_uuid_row,
                document_uuid_row,
                chunk_index,
                page_number,
                dataset_uuid_row,
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
                getattr(row, "dataset_id", None),
            )

    @staticmethod
    def _document_from_chunk_row(row: Any) -> Document:
        (
            chunk_id,
            content,
            doc_metadata,
            tenant_uuid_row,
            document_uuid_row,
            chunk_index,
            page_number,
            dataset_uuid_row,
        ) = Bm25IndexMixin._unpack_chunk_row(row)
        meta = dict(doc_metadata or {})
        meta.setdefault("tenant_id", str(tenant_uuid_row))
        meta.setdefault("document_id", str(document_uuid_row))
        if dataset_uuid_row is not None:
            meta.setdefault("dataset_id", str(dataset_uuid_row))
        meta.setdefault("chunk_index", int(chunk_index) if chunk_index is not None else None)
        meta.setdefault("chunk_id", str(chunk_id))
        meta.setdefault("source", meta.get("source", "unknown"))
        if page_number is not None and not meta.get("page"):
            meta["page"] = page_number
        meta.setdefault("image_id", meta.get("image_id"))
        meta.setdefault("image_url", meta.get("image_url"))
        return Document(page_content=content or "", id=str(chunk_id), metadata=meta)

    @staticmethod
    def _base_completed_chunk_query(db: Session, tenant_uuid: UUID) -> Any:
        query = (
            db.query(
                DocumentChunk.id,
                DocumentChunk.content,
                DocumentChunk.doc_metadata,
                DocumentChunk.tenant_id,
                DocumentChunk.document_id,
                DocumentChunk.chunk_index,
                DocumentChunk.page_number,
                DBDocument.dataset_id,
            )
            .join(DBDocument)
            .filter(DBDocument.status == "completed")
            .filter(DBDocument.publication_status == "published")
            .filter(DocumentChunk.tenant_id == tenant_uuid)
        )
        query = Bm25IndexMixin._query_maybe_call(query, "enable_eagerloads", False)
        return Bm25IndexMixin._query_maybe_call(query, "execution_options", stream_results=True)

    @classmethod
    def _load_chunk_documents(cls, query: Any, *, max_chunks: int = 0, batch_size: int = 2000) -> list[Document]:
        if max_chunks:
            query = query.limit(max_chunks)
        return [cls._document_from_chunk_row(row) for row in cls._iter_query_rows(query, batch_size)]

    def _bm25_scope_cache_ready(
        self,
        *,
        cache_key: str,
        existing_docs: list[Document] | None,
        document_ids: list[UUID] | None,
    ) -> bool:
        if existing_docs is None:
            return False
        if not document_ids:
            self._touch_bm25_cache(cache_key)
            return True
        with self._bm25_cache_lock:
            indexed = self._bm25_doc_ids.get(cache_key)
        if indexed is None:
            self._refresh_bm25_doc_ids(cache_key, existing_docs)
            with self._bm25_cache_lock:
                indexed = self._bm25_doc_ids.get(cache_key) or set()
        requested = {str(did) for did in document_ids if did is not None}
        if requested - set(indexed or set()):
            return False
        self._touch_bm25_cache(cache_key)
        return True

    def _bm25_existing_scope_ready(self, *, cache_key: str, document_ids: list[UUID] | None) -> bool:
        with self._bm25_cache_lock:
            if self._bm25_retrievers.get(cache_key) is None:
                return False
            existing_docs = self._bm25_docs.get(cache_key)
        return self._bm25_scope_cache_ready(
            cache_key=cache_key,
            existing_docs=existing_docs,
            document_ids=document_ids,
        )

    def _bm25_scope_key(
        self,
        *,
        tenant_id: UUID,
        dataset_id: UUID | None = None,
        dataset_ids: tuple[UUID, ...] | None = None,
        document_ids: list[UUID] | None,
    ) -> str:
        """
        Return the in-memory BM25 cache key for a retrieval scope.

        - document_ids scoped: cache per exact document set
        - dataset scoped: cache per (tenant, dataset) to keep indices smaller and easier to invalidate
        - open scope: cache per-tenant (legacy; usually disabled at the API layer)
        """
        tenant_key = self._tenant_key(tenant_id)
        if document_ids:
            normalized_document_ids = sorted({str(document_id) for document_id in document_ids})
            document_scope = ",".join(normalized_document_ids)
            return f"{tenant_key}:documents:{len(normalized_document_ids)}:{stable_hash(document_scope, length=24)}"
        scope_dataset_ids = self._normalize_dataset_scope_ids([dataset_id] if dataset_id is not None else dataset_ids)
        if len(scope_dataset_ids) == 1:
            return f"{tenant_key}:dataset:{scope_dataset_ids[0]}"
        if scope_dataset_ids:
            dataset_suffix = ",".join(str(ds_id) for ds_id in scope_dataset_ids)
            return f"{tenant_key}:datasets:{len(scope_dataset_ids)}:{stable_hash(dataset_suffix, length=24)}"
        return tenant_key

    def _clear_bm25_cache_key(self, key: str) -> None:
        """Clear a single BM25 cache entry (in-memory only)."""
        with self._bm25_cache_lock:
            self._drop_bm25_cache_key_locked(key)

    def _mark_bm25_scope_deferred_locked(self, key: str) -> None:
        self._bm25_deferred_scopes.add(key)
        self._bm25_retrievers.pop(key, None)
        self._bm25_docs.pop(key, None)
        self._bm25_doc_ids.pop(key, None)
        self._chunk_id_lookup.pop(key, None)

    def _mark_bm25_scope_deferred(self, key: str) -> None:
        with self._bm25_cache_lock:
            self._mark_bm25_scope_deferred_locked(key)
        self._touch_bm25_cache(key)

    def _drop_bm25_cache_key_locked(self, key: str) -> None:
        self._bm25_retrievers.pop(key, None)
        self._bm25_docs.pop(key, None)
        self._bm25_doc_ids.pop(key, None)
        self._chunk_id_lookup.pop(key, None)
        self._bm25_deferred_scopes.discard(key)
        self._bm25_cache_versions.pop(key, None)
        self._sparse_doc_vectors.pop(key, None)
        self._colbert_index_cache.pop(key, None)
        self._bm25_cache_order.pop(key, None)
        for locks in (self._bm25_build_locks, self._sparse_build_locks, self._colbert_build_locks):
            lock = locks.get(key)
            if lock is None or not lock.locked():
                locks.pop(key, None)

    def _bm25_dataset_cache_version(
        self,
        *,
        _tenant_id: UUID | None,
        _dataset_ids: tuple[UUID, ...],
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
        dataset_ids = self._normalize_dataset_scope_ids(_dataset_ids)
        if tenant_uuid is None or not dataset_ids:
            return ""

        db = self._open_session()
        try:
            rows = (
                db.query(DBDataset.id, DBDataset.updated_at)
                .filter(DBDataset.tenant_id == tenant_uuid, DBDataset.id.in_(dataset_ids))
                .all()
            )
            updated_by_id = {str(dataset_id): updated_at for dataset_id, updated_at in rows}
            signature_parts: list[str] = []
            for dataset_id in dataset_ids:
                updated_at = updated_by_id.get(str(dataset_id))
                signature_parts.append(f"{dataset_id}:{updated_at.isoformat() if updated_at else ''}")
            signature = "|".join(signature_parts)
            return stable_hash(signature, length=None)
        except Exception as exc:
            _log_retriever_fallback("_bm25_dataset_cache_version", exc)
            return ""
        finally:
            try:
                db.close()
            except Exception as exc:
                logger.debug(NON_CRITICAL_RETRIEVER_FALLBACK_LOG, exc)

    def _get_bm25_build_lock(self, tenant_key: str) -> threading.Lock:
        return self._bm25_build_locks.setdefault(tenant_key, threading.Lock())

    def _bm25_cache_max_tenants(self) -> int:
        try:
            return max(0, int(getattr(settings, "BM25_CACHE_MAX_TENANTS", 0) or 0))
        except (TypeError, ValueError, AttributeError):
            return 0

    @staticmethod
    def _bm25_eager_upsert_max_chunks() -> int:
        try:
            return max(0, int(getattr(settings, "BM25_EAGER_UPSERT_MAX_CHUNKS", 0) or 0))
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
                build_lock = self._bm25_build_locks.get(oldest)
                if oldest == tenant_key or (build_lock is not None and build_lock.locked()):
                    self._bm25_cache_order.move_to_end(oldest)
                    continue
                self._bm25_cache_order.pop(oldest, None)
                evicted.append(oldest)
            for key in evicted:
                self._drop_bm25_cache_key_locked(key)

        if evicted:
            logger.info("BM25 cache evicted %s keys (max=%s)", len(evicted), max_tenants)

    def _missing_bm25_document_ids(
        self,
        *,
        cache_key: str,
        existing_docs: list[Document],
        document_ids: list[UUID],
    ) -> set[str]:
        with self._bm25_cache_lock:
            indexed = self._bm25_doc_ids.get(cache_key)
        if indexed is None:
            self._refresh_bm25_doc_ids(cache_key, existing_docs)
            with self._bm25_cache_lock:
                indexed = self._bm25_doc_ids.get(cache_key) or set()
        requested = {str(did) for did in document_ids if did is not None}
        return requested - set(indexed or set())

    def _load_bm25_scope_documents(
        self,
        db: Session,
        *,
        tenant_uuid: UUID,
        document_ids: list[UUID] | None = None,
        dataset_ids: tuple[UUID, ...] | None = None,
        max_chunks: int = 0,
    ) -> list[Document]:
        query = self._base_completed_chunk_query(db, tenant_uuid)
        if document_ids:
            query = query.filter(DocumentChunk.document_id.in_(document_ids))
        elif dataset_ids:
            query = query.filter(DBDocument.dataset_id.in_(dataset_ids))
        query = query.order_by(DocumentChunk.document_id.asc(), DocumentChunk.chunk_index.asc())
        return self._load_chunk_documents(query, max_chunks=max_chunks)

    def _rebuild_bm25_scope_for_documents(
        self,
        db: Session,
        *,
        tenant_uuid: UUID,
        cache_key: str,
        document_ids: list[UUID],
        missing_count: int,
        max_chunks: int,
    ) -> None:
        docs = self._load_bm25_scope_documents(
            db,
            tenant_uuid=tenant_uuid,
            document_ids=document_ids,
            max_chunks=max_chunks,
        )
        if not docs:
            return
        self._build_bm25_index_from_documents(docs, tenant_id=tenant_uuid, cache_key=cache_key)
        logger.info(
            "BM25 lazy-built (scoped rebuild) %s chunks for tenant %s missing_docs=%s cap=%s",
            len(docs),
            cache_key,
            missing_count,
            max_chunks,
        )

    def _extend_bm25_scope_for_missing_documents(
        self,
        db: Session,
        *,
        tenant_uuid: UUID,
        cache_key: str,
        missing: set[str],
        existing_count: int,
        max_chunks: int,
    ) -> None:
        remaining = max(0, int(max_chunks) - int(existing_count)) if max_chunks else 0
        if max_chunks and remaining <= 0:
            return
        missing_ids = [UUID(doc_id) for doc_id in missing]
        bm25_docs = self._load_bm25_scope_documents(
            db,
            tenant_uuid=tenant_uuid,
            document_ids=missing_ids,
            max_chunks=remaining,
        )
        if not bm25_docs:
            return
        with self._bm25_cache_lock:
            existing_docs = list(self._bm25_docs.get(cache_key) or [])
        merged_docs = self._merge_bm25_scope_docs(
            existing_docs,
            self._prepare_bm25_upsert_docs(bm25_docs),
        )
        self._replace_bm25_scope_index(cache_key=cache_key, merged_docs=merged_docs)
        logger.info(
            "BM25 lazy-extended %s chunks for scope %s (missing_docs=%s)",
            len(bm25_docs),
            cache_key,
            len(missing),
        )

    def _handle_missing_bm25_scope_docs(
        self,
        db: Session,
        *,
        tenant_uuid: UUID,
        cache_key: str,
        existing_docs: list[Document] | None,
        document_ids: list[UUID] | None,
        max_chunks: int,
    ) -> bool | None:
        if existing_docs is None or not document_ids:
            return None
        missing = self._missing_bm25_document_ids(
            cache_key=cache_key,
            existing_docs=existing_docs,
            document_ids=document_ids,
        )
        if not missing:
            self._touch_bm25_cache(cache_key)
            return True
        existing_count = len(existing_docs)
        if max_chunks and existing_count >= max_chunks:
            self._rebuild_bm25_scope_for_documents(
                db,
                tenant_uuid=tenant_uuid,
                cache_key=cache_key,
                document_ids=document_ids,
                missing_count=len(missing),
                max_chunks=max_chunks,
            )
            return True
        self._extend_bm25_scope_for_missing_documents(
            db,
            tenant_uuid=tenant_uuid,
            cache_key=cache_key,
            missing=missing,
            existing_count=existing_count,
            max_chunks=max_chunks,
        )
        return True

    def _build_initial_bm25_scope(
        self,
        db: Session,
        *,
        tenant_uuid: UUID,
        cache_key: str,
        document_ids: list[UUID] | None,
        dataset_ids: tuple[UUID, ...],
        max_chunks: int,
    ) -> bool:
        docs = self._load_bm25_scope_documents(
            db,
            tenant_uuid=tenant_uuid,
            document_ids=document_ids,
            dataset_ids=dataset_ids,
            max_chunks=max_chunks,
        )
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

    @staticmethod
    def _bm25_lazy_build_enabled() -> bool:
        return bool(getattr(settings, "BM25_INDEX_ENABLED", True)) and bool(
            getattr(settings, "BM25_LAZY_BUILD_ENABLED", True)
        )

    @staticmethod
    def _can_lazy_build_scope(*, document_ids: list[UUID] | None, dataset_ids: tuple[UUID, ...]) -> bool:
        full_tenant = bool(getattr(settings, "BM25_LAZY_BUILD_FULL_TENANT", False))
        return bool(document_ids or full_tenant or dataset_ids)

    def _build_bm25_scope_inside_lock(
        self,
        *,
        tenant_uuid: UUID,
        cache_key: str,
        document_ids: list[UUID] | None,
        dataset_ids: tuple[UUID, ...],
    ) -> bool:
        with self._bm25_cache_lock:
            existing_retriever = self._bm25_retrievers.get(cache_key)
            existing_docs = self._bm25_docs.get(cache_key)
        if existing_retriever is not None and self._bm25_scope_cache_ready(
            cache_key=cache_key,
            existing_docs=existing_docs,
            document_ids=document_ids,
        ):
            return True
        if not self._can_lazy_build_scope(document_ids=document_ids, dataset_ids=dataset_ids):
            return False

        if existing_retriever is None and existing_docs is not None and existing_docs:
            self._build_bm25_index_from_documents(existing_docs, tenant_id=tenant_uuid, cache_key=cache_key)
            logger.info(
                "BM25 lazy-built %s cached chunks for scope %s",
                len(existing_docs),
                cache_key,
            )
            return True

        max_chunks = max(0, int(getattr(settings, "BM25_LAZY_BUILD_MAX_CHUNKS", 0) or 0))
        db = self._open_session()
        try:
            if existing_retriever is not None and existing_docs is not None and document_ids:
                handled = self._handle_missing_bm25_scope_docs(
                    db,
                    tenant_uuid=tenant_uuid,
                    cache_key=cache_key,
                    existing_docs=existing_docs,
                    document_ids=document_ids,
                    max_chunks=max_chunks,
                )
                if handled is not None:
                    return handled

            return self._build_initial_bm25_scope(
                db,
                tenant_uuid=tenant_uuid,
                cache_key=cache_key,
                document_ids=document_ids,
                dataset_ids=dataset_ids,
                max_chunks=max_chunks,
            )
        except Exception as exc:
            logger.warning("BM25 lazy build failed for scope %s: %s", cache_key, str(exc)[:200])
            return False
        finally:
            try:
                db.close()
            except Exception as exc:
                logger.debug(NON_CRITICAL_RETRIEVER_FALLBACK_LOG, exc)

    def _lazy_build_bm25_index(
        self,
        *,
        tenant_id: UUID | None,
        document_ids: list[UUID] | None,
        dataset_ids: tuple[UUID, ...] = (),
    ) -> bool:
        """Build BM25 index on-demand to mitigate cold-start in multi-process deployments."""
        if not self._bm25_lazy_build_enabled():
            return False

        tenant_uuid = self._resolve_tenant_uuid(tenant_id)
        if tenant_uuid is None:
            return False

        cache_key = self._bm25_scope_key(
            tenant_id=tenant_uuid,
            dataset_ids=dataset_ids,
            document_ids=document_ids,
        )
        if self._bm25_existing_scope_ready(cache_key=cache_key, document_ids=document_ids):
            return True

        lock = self._get_bm25_build_lock(cache_key)
        with lock:
            return self._build_bm25_scope_inside_lock(
                tenant_uuid=tenant_uuid,
                cache_key=cache_key,
                document_ids=document_ids,
                dataset_ids=dataset_ids,
            )

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
        with self._bm25_cache_lock:
            self._bm25_deferred_scopes.discard(key)
            self._bm25_retrievers[key] = retriever
            self._bm25_docs[key] = docs
            self._refresh_bm25_doc_ids(key, docs)
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

    def _count_retrieval_docs_in_db(
        self,
        db: Session,
        *,
        tenant_id: UUID,
        dataset_id: UUID | None = None,
        document_ids: list[UUID] | None = None,
    ) -> int:
        q = (
            db.query(func.count(DocumentChunk.id))
            .join(DBDocument)
            .filter(DBDocument.status == "completed")
            .filter(DBDocument.publication_status == "published")
            .filter(DocumentChunk.tenant_id == tenant_id)
        )
        if dataset_id is not None:
            q = q.filter(DBDocument.dataset_id == dataset_id)
        if document_ids:
            q = q.filter(DocumentChunk.document_id.in_(document_ids))
        return int(q.scalar() or 0)

    def _raise_retrieval_rebuild_limit_exceeded(
        self,
        *,
        chunk_count: int,
        limit: int,
        tenant_id: UUID,
        dataset_id: UUID | None = None,
        document_ids: list[UUID] | None = None,
    ) -> None:
        raise RuntimeError(
            "Retrieval rebuild aborted: "
            f"scope has {int(chunk_count)} published chunks, exceeds "
            f"RETRIEVAL_REBUILD_MAX_CHUNKS={int(limit)} "
            f"(tenant_id={tenant_id}, dataset_id={dataset_id}, document_ids={len(document_ids or [])}). "
            "Narrow the rebuild scope or raise RETRIEVAL_REBUILD_MAX_CHUNKS."
        )

    def _load_retrieval_docs_for_rebuild(
        self,
        db: Session,
        *,
        tenant_id: UUID,
        dataset_id: UUID | None = None,
        document_ids: list[UUID] | None = None,
        batch_size: int = 2000,
    ) -> list[Document]:
        rebuild_limit = max(0, int(getattr(settings, "RETRIEVAL_REBUILD_MAX_CHUNKS", 0) or 0))
        if rebuild_limit > 0:
            scope_count = self._count_retrieval_docs_in_db(
                db,
                tenant_id=tenant_id,
                dataset_id=dataset_id,
                document_ids=document_ids,
            )
            if scope_count > rebuild_limit:
                self._raise_retrieval_rebuild_limit_exceeded(
                    chunk_count=scope_count,
                    limit=rebuild_limit,
                    tenant_id=tenant_id,
                    dataset_id=dataset_id,
                    document_ids=document_ids,
                )

        load_limit = rebuild_limit + 1 if rebuild_limit > 0 else 0
        docs = self._load_retrieval_docs_from_db(
            db,
            tenant_id=tenant_id,
            dataset_id=dataset_id,
            document_ids=document_ids,
            max_chunks=load_limit,
            batch_size=batch_size,
        )
        if rebuild_limit > 0 and len(docs) > rebuild_limit:
            self._raise_retrieval_rebuild_limit_exceeded(
                chunk_count=len(docs),
                limit=rebuild_limit,
                tenant_id=tenant_id,
                dataset_id=dataset_id,
                document_ids=document_ids,
            )
        return docs

    def rebuild_bm25_index_for_operational_scope(
        self,
        db: Session,
        *,
        tenant_id: UUID,
        dataset_id: UUID | None = None,
        document_ids: list[UUID] | None = None,
        batch_size: int = 2000,
    ) -> int:
        docs = self._load_retrieval_docs_for_rebuild(
            db,
            tenant_id=tenant_id,
            dataset_id=dataset_id,
            document_ids=document_ids,
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
            docs.append(
                self._prepare_retrieval_document(Document(page_content=content or "", id=str(chunk_id), metadata=meta))
            )
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
        docs = self._load_retrieval_docs_for_rebuild(
            db,
            tenant_id=tenant_id,
            dataset_id=dataset_id,
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

    def _prepare_bm25_upsert_docs(self, docs: list[Document]) -> list[Document]:
        return [self._prepare_retrieval_document(doc) for doc in docs if doc is not None]

    @staticmethod
    def _infer_single_dataset_scope_from_docs(docs: list[Document]) -> UUID | None:
        dataset_ids: set[UUID] = set()
        for doc in docs:
            meta = doc.metadata or {}
            raw_dataset_id = meta.get("dataset_id")
            if raw_dataset_id in (None, ""):
                continue
            try:
                dataset_ids.add(UUID(str(raw_dataset_id)))
            except (TypeError, ValueError):
                return None
            if len(dataset_ids) > 1:
                return None
        return next(iter(dataset_ids)) if dataset_ids else None

    @staticmethod
    def _merge_bm25_scope_docs(existing: list[Document], upsert_docs: list[Document]) -> list[Document]:
        merged: dict[str, Document] = {str(d.id): d for d in existing if d.id is not None}
        for d in upsert_docs:
            if d.id is not None:
                merged[str(d.id)] = d
        return list(merged.values())

    @staticmethod
    def _build_chunk_id_lookup(merged_docs: list[Document]) -> dict[str, str]:
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
        return lookup

    def _replace_bm25_scope_index(self, *, cache_key: str, merged_docs: list[Document]) -> None:
        retriever = BM25Retriever.from_documents(
            merged_docs,
            preprocess_func=self._bm25_tokenize,
            k=10,
        )
        lookup = self._build_chunk_id_lookup(merged_docs)
        with self._bm25_cache_lock:
            self._bm25_deferred_scopes.discard(cache_key)
            self._bm25_retrievers[cache_key] = retriever
            self._bm25_docs[cache_key] = merged_docs
            self._refresh_bm25_doc_ids(cache_key, merged_docs)
            self._chunk_id_lookup[cache_key] = lookup
            self._touch_bm25_cache(cache_key)

    def _defer_bm25_scope_index(self, *, cache_key: str, merged_docs: list[Document]) -> None:
        del merged_docs
        self._mark_bm25_scope_deferred(cache_key)

    def _load_bm25_scope_documents_for_deferred_upsert(
        self,
        *,
        tenant_uuid: UUID,
        dataset_scope_ids: tuple[UUID, ...],
        cache_key: str,
        db: Session | None = None,
    ) -> list[Document] | None:
        # Reuse the caller's session when one is supplied: the deferred corpus refresh
        # runs inside the same transaction that just wrote the chunks, so a fresh
        # SessionLocal() would not see them yet and the sparse/ColBERT sync below would
        # be built from a stale corpus.
        session = db if db is not None else self._open_session()
        owns_session = db is None
        try:
            return self._load_bm25_scope_documents(
                session,
                tenant_uuid=tenant_uuid,
                dataset_ids=dataset_scope_ids,
            )
        except Exception as exc:
            logger.warning("BM25 deferred corpus refresh failed for scope %s: %s", cache_key, str(exc)[:200])
            return None
        finally:
            if owns_session:
                try:
                    session.close()
                except Exception as exc:
                    logger.debug(NON_CRITICAL_RETRIEVER_FALLBACK_LOG, exc)

    def _clear_bm25_document_scope_caches(self, *, tenant_key: str) -> None:
        document_scope_prefix = f"{tenant_key}:documents:"
        with self._bm25_cache_lock:
            document_scope_keys = [
                key
                for key in set(self._bm25_docs) | set(self._bm25_retrievers) | set(self._bm25_deferred_scopes)
                if str(key).startswith(document_scope_prefix)
            ]
            for key in document_scope_keys:
                self._drop_bm25_cache_key_locked(key)

    def _resolve_bm25_upsert_dataset_scope_ids(self, upsert_docs: list[Document]) -> tuple[UUID, ...]:
        dataset_scope_ids = self._explicit_dataset_scope_ids()
        if dataset_scope_ids:
            return dataset_scope_ids
        inferred_dataset_id = self.dataset_id or self._infer_single_dataset_scope_from_docs(upsert_docs)
        return self._normalize_dataset_scope_ids([inferred_dataset_id] if inferred_dataset_id is not None else None)

    def _merge_bm25_upsert_scope_documents(
        self,
        *,
        cache_key: str,
        tenant_uuid: UUID,
        dataset_scope_ids: tuple[UUID, ...],
        upsert_docs: list[Document],
        sync_needs_corpus: bool,
        db: Session | None,
    ) -> tuple[bool, list[Document] | None]:
        with self._bm25_cache_lock:
            existing = list(self._bm25_docs.get(cache_key) or [])
            scope_deferred = cache_key in self._bm25_deferred_scopes
        if scope_deferred and not existing and sync_needs_corpus:
            existing = self._load_bm25_scope_documents_for_deferred_upsert(
                tenant_uuid=tenant_uuid,
                dataset_scope_ids=dataset_scope_ids,
                cache_key=cache_key,
                db=db,
            )
            if existing is None:
                return scope_deferred, None
        return scope_deferred, self._merge_bm25_scope_docs(existing, upsert_docs)

    def _store_bm25_upsert_scope(
        self,
        *,
        cache_key: str,
        scope_deferred: bool,
        merged_docs: list[Document] | None,
        eager_limit: int,
        upsert_docs: list[Document],
    ) -> None:
        if scope_deferred:
            self._defer_bm25_scope_index(cache_key=cache_key, merged_docs=merged_docs or [])
            logger.info(
                "BM25 deferred scope retained for %s after upsert chunks=%s corpus_refresh=%s",
                cache_key,
                len(upsert_docs),
                bool(merged_docs is not None),
            )
            return
        if merged_docs is not None and eager_limit > 0 and len(merged_docs) > eager_limit:
            self._defer_bm25_scope_index(cache_key=cache_key, merged_docs=merged_docs)
            logger.info(
                "BM25 index rebuild deferred for scope %s chunks=%s eager_limit=%s",
                cache_key,
                len(merged_docs),
                eager_limit,
            )
            return
        self._replace_bm25_scope_index(cache_key=cache_key, merged_docs=merged_docs or [])
        logger.info("BM25 index updated to %s chunks for scope %s", len(merged_docs or []), cache_key)

    def upsert_bm25_documents(
        self,
        docs: list[Document],
        tenant_id: UUID | None = None,
        *,
        db: Session | None = None,
    ):
        """
        Incrementally update BM25 index (avoids full DB scan each time).
        Note: BM25Retriever itself doesn't support incremental training, so we merge in-memory and rebuild.
        This still significantly reduces DB query overhead, suitable for large-scale knowledge bases.

        Pass ``db`` when calling from inside an open write transaction so a deferred-scope
        corpus refresh reads the chunks that transaction just wrote.
        """
        if not docs:
            return
        tenant_uuid = self._resolve_tenant_uuid(tenant_id)
        if tenant_uuid is None:
            return
        upsert_docs = self._prepare_bm25_upsert_docs(docs)
        if not upsert_docs:
            return

        self._clear_candidate_corpus_token_cache(tenant_uuid)
        tenant_key = self._tenant_key(tenant_uuid)
        self._clear_bm25_document_scope_caches(tenant_key=tenant_key)
        dataset_scope_ids = self._resolve_bm25_upsert_dataset_scope_ids(upsert_docs)
        cache_key = self._bm25_scope_key(
            tenant_id=tenant_uuid,
            dataset_ids=dataset_scope_ids,
            document_ids=None,
        )
        sync_needs_corpus = self._effective_sparse_enabled() or bool(
            getattr(settings, "COLBERT_RETRIEVAL_ENABLED", False)
        )
        merged_docs: list[Document] | None = None
        with self._get_bm25_build_lock(cache_key):
            scope_deferred, merged_docs = self._merge_bm25_upsert_scope_documents(
                cache_key=cache_key,
                tenant_uuid=tenant_uuid,
                dataset_scope_ids=dataset_scope_ids,
                upsert_docs=upsert_docs,
                sync_needs_corpus=sync_needs_corpus,
                db=db,
            )
            eager_limit = self._bm25_eager_upsert_max_chunks()
            self._store_bm25_upsert_scope(
                cache_key=cache_key,
                scope_deferred=scope_deferred,
                merged_docs=merged_docs,
                eager_limit=eager_limit,
                upsert_docs=upsert_docs,
            )

        if merged_docs is not None:
            self._sync_sparse_index_after_bm25_upsert(
                cache_key=cache_key,
                tenant_id=tenant_uuid,
                dataset_scope_ids=dataset_scope_ids,
                merged_docs=merged_docs,
                upsert_docs=upsert_docs,
            )
            self._sync_colbert_index_after_bm25_upsert(
                cache_key=cache_key,
                merged_docs=merged_docs,
                upsert_docs=upsert_docs,
            )

    def remove_document_from_bm25_index(self, document_id: UUID, tenant_id: UUID | None = None):
        """Remove all chunks of a specified document from the BM25 index."""
        self.remove_from_bm25_index_by_metadata_filter(
            tenant_id=tenant_id,
            metadata_filter={"document_id": {"$eq": str(document_id)}},
        )

    def _bm25_filter_scope_keys(self, *, tenant_key: str) -> list[str]:
        scope_prefixes = (
            f"{tenant_key}:dataset:",
            f"{tenant_key}:datasets:",
            f"{tenant_key}:documents:",
        )
        with self._bm25_cache_lock:
            scope_keys = [
                k
                for k in set(self._bm25_docs) | set(self._bm25_retrievers) | set(self._bm25_deferred_scopes)
                if k == tenant_key or str(k).startswith(scope_prefixes)
            ]
        return scope_keys or [tenant_key]

    def _clear_bm25_scope_after_filter_delete(self, *, scope_key: str, removed: int) -> None:
        with self._bm25_cache_lock:
            self._drop_bm25_cache_key_locked(scope_key)
        logger.info(
            "BM25 index cleared for scope %s after filtered deletion (removed=%s)",
            scope_key,
            removed,
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
        self._clear_candidate_corpus_token_cache(tenant_id)
        total_removed = 0
        for scope_key in self._bm25_filter_scope_keys(tenant_key=tenant_key):
            with self._get_bm25_build_lock(scope_key):
                with self._bm25_cache_lock:
                    existing = list(self._bm25_docs.get(scope_key) or [])
                if not existing:
                    continue

                before_ids = {str(d.id) for d in existing if d is not None and d.id is not None}
                filtered = [d for d in existing if not self._match_metadata_filter((d.metadata or {}), metadata_filter)]
                after_ids = {str(d.id) for d in filtered if d is not None and d.id is not None}

                removed = int(len(existing) - len(filtered))
                if removed <= 0:
                    continue

                removed_ids = before_ids - after_ids

                if not filtered:
                    self._clear_bm25_scope_after_filter_delete(scope_key=scope_key, removed=removed)
                    total_removed += removed
                    continue

                self._replace_bm25_scope_index(cache_key=scope_key, merged_docs=filtered)

            if removed_ids:
                self._remove_sparse_vectors_for_deleted_chunks(scope_key=scope_key, removed_ids=removed_ids)
                self._remove_colbert_vectors_for_deleted_chunks(
                    scope_key=scope_key,
                    removed_ids=removed_ids,
                    filtered=filtered,
                )

            logger.info("BM25 index removed %s docs by metadata_filter for scope %s", removed, scope_key)
            total_removed += removed

        return total_removed

    def clear_bm25_cache(self) -> None:
        """Clear all cached BM25 indices (in-memory only)."""
        with self._bm25_cache_lock:
            self._bm25_retrievers.clear()
            self._bm25_docs.clear()
            self._bm25_doc_ids.clear()
            self._chunk_id_lookup.clear()
            self._bm25_deferred_scopes.clear()
            self._bm25_build_locks.clear()
            self._bm25_cache_versions.clear()
            self._corpus_token_cache.clear()
            self._sparse_doc_vectors.clear()
            self._sparse_build_locks.clear()
            self._colbert_index_cache.clear()
            self._colbert_build_locks.clear()
            self._bm25_cache_order.clear()

    def _bm25_search_scope(
        self,
        *,
        tenant_id: UUID | None,
        document_ids: list[UUID] | None,
        metadata_filter: dict[str, Any] | None = None,
    ) -> tuple[UUID | None, tuple[UUID, ...], str | None]:
        tenant_uuid = self._resolve_tenant_uuid(tenant_id)
        if tenant_uuid is None:
            return None, (), None
        dataset_scope_ids = self._dataset_scope_ids(document_ids)
        if not dataset_scope_ids and not (document_ids or []):
            dataset_scope_ids = self._normalize_dataset_scope_ids(
                self._collect_lexical_dataset_scope(metadata_filter),
            )
        cache_key = self._bm25_scope_key(
            tenant_id=tenant_uuid,
            dataset_ids=dataset_scope_ids,
            document_ids=document_ids,
        )
        return tenant_uuid, dataset_scope_ids, cache_key

    def _refresh_bm25_dataset_cache_version(
        self,
        *,
        cache_key: str,
        tenant_uuid: UUID,
        dataset_scope_ids: tuple[UUID, ...],
        document_ids: list[UUID] | None = None,
    ) -> str | None:
        if document_ids:
            document_scope_ids = list(dict.fromkeys(document_ids))
            current_version = self._resolve_candidate_cache_corpus_token(
                tenant_id=tenant_uuid,
                document_ids=document_scope_ids,
            )
        elif dataset_scope_ids:
            current_version = self._bm25_dataset_cache_version(
                _tenant_id=tenant_uuid,
                _dataset_ids=dataset_scope_ids,
            )
        else:
            return None
        if not current_version:
            return None

        with self._bm25_cache_lock:
            cached_version = self._bm25_cache_versions.get(cache_key)
            cache_exists = (
                self._bm25_retrievers.get(cache_key) is not None
                or bool(self._bm25_docs.get(cache_key))
                or cache_key in self._bm25_deferred_scopes
            )

        if cache_exists and (cached_version is None or cached_version != current_version):
            self._clear_bm25_cache_key(cache_key)
        return current_version

    def _ensure_bm25_search_index(
        self,
        *,
        cache_key: str,
        tenant_uuid: UUID,
        dataset_scope_ids: tuple[UUID, ...],
        document_ids: list[UUID] | None,
    ) -> tuple[BM25Retriever | None, list[Document] | None]:
        with self._bm25_cache_lock:
            retriever = self._bm25_retrievers.get(cache_key)
            docs = self._bm25_docs.get(cache_key)
        if (
            retriever is not None
            and docs is not None
            and self._bm25_scope_cache_ready(
                cache_key=cache_key,
                existing_docs=docs,
                document_ids=document_ids,
            )
        ):
            self._last_bm25_status.update(
                {
                    "cache_ready_before": True,
                    "cache_ready_after": True,
                    "lazy_build_attempted": False,
                    "lazy_build_success": False,
                    "reason": "cache_hit",
                }
            )
            return retriever, docs
        lazy_attempted = self._bm25_lazy_build_enabled() and self._can_lazy_build_scope(
            document_ids=document_ids,
            dataset_ids=dataset_scope_ids,
        )
        lazy_success = self._lazy_build_bm25_index(
            tenant_id=tenant_uuid,
            document_ids=document_ids,
            dataset_ids=dataset_scope_ids,
        )
        with self._bm25_cache_lock:
            retriever = self._bm25_retrievers.get(cache_key)
            docs = self._bm25_docs.get(cache_key)
        cache_ready_after = bool(retriever is not None and docs is not None)
        if cache_ready_after:
            reason = "lazy_build_success" if lazy_attempted else "cache_ready"
        elif not lazy_attempted:
            reason = "lazy_build_not_available"
        else:
            reason = "lazy_build_failed_or_empty"
        self._last_bm25_status.update(
            {
                "cache_ready_before": False,
                "cache_ready_after": cache_ready_after,
                "lazy_build_attempted": bool(lazy_attempted),
                "lazy_build_success": bool(lazy_success and cache_ready_after),
                "reason": reason,
            }
        )
        return retriever, docs

    def _bm25_result_allowed(
        self,
        *,
        metadata: dict[str, Any],
        allowed_ids: set[str] | None,
        metadata_filter: dict[str, Any] | None,
    ) -> bool:
        if allowed_ids and str(metadata.get("document_id")) not in allowed_ids:
            return False
        return not (
            metadata_filter
            and self.metadata_filter_enabled
            and not self._match_metadata_filter(metadata, metadata_filter)
        )

    @staticmethod
    def _candidate_metadata_from_doc(meta: dict[str, Any], *, chunk_id: Any = None) -> dict[str, Any]:
        pipeline_meta = meta.get("pipeline") if isinstance(meta.get("pipeline"), dict) else {}
        out = {
            "tenant_id": meta.get("tenant_id"),
            "dataset_id": meta.get("dataset_id"),
            "document_id": meta.get("document_id"),
            "source": meta.get("source", "unknown"),
            "page": meta.get("page"),
            "page_number": meta.get("page_number"),
            "chunk_index": meta.get("chunk_index"),
            "chunk_id": meta.get("chunk_id") or chunk_id,
            "img_id": meta.get("img_id"),
            "image_id": meta.get("image_id"),
            "image_url": meta.get("image_url"),
        }
        for key in _PIPELINE_PLUGIN_METADATA_KEYS:
            value = meta.get(key) or pipeline_meta.get(key)
            if value:
                out[key] = value
        for key in _PLATFORM_METADATA_VIEW_KEYS:
            value = meta.get(key)
            if isinstance(value, dict) and value:
                out[key] = value
        return out

    def _bm25_result_from_doc(
        self,
        *,
        doc: Document,
        raw_score: Any,
        final_score: float,
        question_channel_score: float,
    ) -> dict[str, Any]:
        meta = doc.metadata or {}
        out_meta = self._candidate_metadata_from_doc(meta, chunk_id=doc.id)
        out_meta.update(
            {
                "bm25_score": float(final_score),
                "bm25_score_raw": float(raw_score),
                "question_channel_score": float(question_channel_score),
            }
        )
        return {
            "chunk_id": doc.id,
            "content": self._result_content_from_doc(doc),
            "metadata": out_meta,
            "score": float(final_score),
        }

    def _bm25_results_from_scores(
        self,
        *,
        docs: list[Document],
        scores: Any,
        query_tokens: list[str],
        allowed_ids: set[str] | None,
        metadata_filter: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for doc, score in zip(docs, scores, strict=False):
            meta = doc.metadata or {}
            if not self._bm25_result_allowed(metadata=meta, allowed_ids=allowed_ids, metadata_filter=metadata_filter):
                continue
            question_channel_score = self._question_channel_overlap_score(query_tokens=query_tokens, metadata=meta)
            final_score = float(score) + float(question_channel_score or 0.0)
            results.append(
                self._bm25_result_from_doc(
                    doc=doc,
                    raw_score=score,
                    final_score=final_score,
                    question_channel_score=question_channel_score,
                )
            )
        return results

    def _search_bm25(
        self,
        query: str,
        top_k: int = 10,
        document_ids: list[UUID] | None = None,
        tenant_id: UUID | None = None,
        metadata_filter: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """BM25 keyword retrieval (internal use, returns dicts with scores)."""
        self._last_bm25_status = {
            "index_enabled": bool(getattr(settings, "BM25_INDEX_ENABLED", True)),
            "lazy_build_enabled": bool(self._bm25_lazy_build_enabled()),
            "lazy_build_full_tenant": bool(getattr(settings, "BM25_LAZY_BUILD_FULL_TENANT", False)),
            "lazy_build_max_chunks": max(0, int(getattr(settings, "BM25_LAZY_BUILD_MAX_CHUNKS", 0) or 0)),
            "cache_ready_before": False,
            "cache_ready_after": False,
            "lazy_build_attempted": False,
            "lazy_build_success": False,
            "scope": "unknown",
            "reason": "not_run",
        }
        if not bool(getattr(settings, "BM25_INDEX_ENABLED", True)):
            self._last_bm25_status["reason"] = "index_disabled"
            return []

        tenant_uuid, dataset_scope_ids, cache_key = self._bm25_search_scope(
            tenant_id=tenant_id,
            document_ids=document_ids,
            metadata_filter=metadata_filter,
        )
        if document_ids:
            scope_kind = "documents"
        elif dataset_scope_ids:
            scope_kind = "dataset"
        else:
            scope_kind = "tenant"
        self._last_bm25_status.update(
            {
                "scope": scope_kind,
                "cache_key_type": scope_kind,
                "document_scope_count": len(document_ids or []),
                "dataset_scope": bool(dataset_scope_ids),
            }
        )
        if tenant_uuid is None or cache_key is None:
            self._last_bm25_status["reason"] = "missing_tenant_or_scope"
            return []

        current_version = self._refresh_bm25_dataset_cache_version(
            cache_key=cache_key,
            tenant_uuid=tenant_uuid,
            dataset_scope_ids=dataset_scope_ids,
            document_ids=document_ids,
        )
        retriever, docs = self._ensure_bm25_search_index(
            cache_key=cache_key,
            tenant_uuid=tenant_uuid,
            dataset_scope_ids=dataset_scope_ids,
            document_ids=document_ids,
        )
        if retriever is None or docs is None:
            logger.warning("BM25 index not initialized, skipping keyword search")
            self._last_bm25_status["cache_ready_after"] = False
            self._last_bm25_status.setdefault("reason", "index_unavailable")
            return []
        if current_version:
            with self._bm25_cache_lock:
                self._bm25_cache_versions[cache_key] = current_version

        self._touch_bm25_cache(cache_key)
        self._last_bm25_status.update(
            {
                "cache_ready_after": True,
                "indexed_docs": len(docs or []),
            }
        )

        allowed_ids = {str(doc_id) for doc_id in document_ids} if document_ids else None
        processed_query = retriever.preprocess_func(query)
        scores = retriever.vectorizer.get_scores(processed_query)  # type: ignore[attr-defined]
        query_tokens = [str(token or "").strip() for token in processed_query if str(token or "").strip()]
        results = self._bm25_results_from_scores(
            docs=docs,
            scores=scores,
            query_tokens=query_tokens,
            allowed_ids=allowed_ids,
            metadata_filter=metadata_filter,
        )
        out = self._top_scored_results(results, top_k)
        self._last_bm25_status.update(
            {
                "query_tokens": len(query_tokens),
                "candidates": len(out),
                "reason": "ok",
            }
        )
        return out

    def _bm25_scope_docs(
        self,
        *,
        tenant_id: UUID | None,
        document_ids: list[UUID] | None,
        metadata_filter: dict[str, Any] | None = None,
    ) -> tuple[UUID | None, tuple[UUID, ...], str | None, list[Document]]:
        tenant_uuid, dataset_scope_ids, cache_key = self._bm25_search_scope(
            tenant_id=tenant_id,
            document_ids=document_ids,
            metadata_filter=metadata_filter,
        )
        if tenant_uuid is None or cache_key is None:
            return None, (), None, []
        with self._bm25_cache_lock:
            docs = list(self._bm25_docs.get(cache_key) or [])
        return tenant_uuid, dataset_scope_ids, cache_key, docs

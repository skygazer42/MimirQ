"""Shared native BM25 lifecycle and explicit snapshots for derived test indexes."""

import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from langchain_core.documents import Document
from sqlalchemy import func, or_, tuple_
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.document import Document as DBDocument
from app.models.document import DocumentChunk
from app.rag.core.hashing import stable_hash
from app.rag.preprocessing.tokenization import tokenize_lexical_text
from app.rag.retrieval.corpus_artifacts import ColbertCorpusIndex, CorpusArtifacts, SparseCorpusIndex
from app.rag.retrieval.hybrid.common import _log_retriever_fallback
from app.rag.retrieval.hybrid.text_preparation import prepare_retrieval_document
from app.services import corpus_cache_tokens
from app.storage.bm25.milvus import MilvusBM25Store, get_bm25_store


@dataclass(frozen=True)
class CorpusScope:
    tenant_id: UUID
    dataset_ids: tuple[UUID, ...] = ()
    document_ids: tuple[UUID, ...] = ()


@dataclass(frozen=True)
class CorpusSnapshot:
    scope: CorpusScope
    cache_key: str
    documents: tuple[Document, ...]


@dataclass(frozen=True)
class CorpusSearchResult:
    records: list[dict[str, Any]]
    status: dict[str, Any]


def is_milvus_bm25_enabled() -> bool:
    """Check native BM25 configuration without probing the storage service."""
    return settings.BM25_INDEX_ENABLED and settings.VECTOR_BACKEND.strip().lower() == "milvus"


class CorpusIndex:
    def __init__(self, *, bm25_store: MilvusBM25Store | None = None) -> None:
        self._store = bm25_store if bm25_store is not None else get_bm25_store()
        self._lock = threading.RLock()
        self._corpus_token_cache: OrderedDict[tuple, tuple[float, str]] = OrderedDict()
        self._corpus_artifacts = CorpusArtifacts(sparse=SparseCorpusIndex(), colbert=ColbertCorpusIndex())

    @property
    def artifacts(self) -> CorpusArtifacts:
        return self._corpus_artifacts

    @staticmethod
    def _open_session() -> Session:
        return SessionLocal()

    _tokenize_lexical_text = staticmethod(tokenize_lexical_text)

    @staticmethod
    def _normalize_dataset_scope_ids(dataset_ids) -> tuple[UUID, ...]:
        return tuple(sorted(set(dataset_ids or ()), key=str))

    @staticmethod
    def _prepare_retrieval_document(document: Document) -> Document:
        return prepare_retrieval_document(document, log_fallback=_log_retriever_fallback)

    @staticmethod
    def scope_key(scope: CorpusScope) -> str:
        tenant = str(scope.tenant_id)
        if scope.document_ids:
            ids = sorted(set(map(str, scope.document_ids)))
            return f"{tenant}:documents:{len(ids)}:{stable_hash(','.join(ids), length=24)}"
        datasets = sorted(set(map(str, scope.dataset_ids)))
        if len(datasets) == 1:
            return f"{tenant}:dataset:{datasets[0]}"
        if datasets:
            return f"{tenant}:datasets:{len(datasets)}:{stable_hash(','.join(datasets), length=24)}"
        return tenant

    def search(
        self, query: str, *, scope: CorpusScope, top_k: int, metadata_filter: dict[str, Any] | None
    ) -> CorpusSearchResult:
        if scope.tenant_id is None:
            raise ValueError("Corpus search requires an explicit tenant")
        status = {
            "provider": "milvus_bm25",
            "index_enabled": is_milvus_bm25_enabled(),
            "scope": "documents" if scope.document_ids else "dataset" if scope.dataset_ids else "tenant",
        }
        if not is_milvus_bm25_enabled():
            return CorpusSearchResult(
                [],
                {
                    **status,
                    "reason": "requires_milvus"
                    if settings.VECTOR_BACKEND.strip().lower() != "milvus"
                    else "index_disabled",
                },
            )
        records = self._store.search(
            query,
            tenant_id=scope.tenant_id,
            dataset_ids=scope.dataset_ids,
            document_ids=scope.document_ids,
            metadata_filter=metadata_filter,
            top_k=top_k,
        )
        return CorpusSearchResult(
            records, {**status, "candidates": len(records), "reason": "ok" if records else "no_candidates"}
        )

    def upsert(self, db: Session | None, *, tenant_id: UUID, documents: list[Document]) -> None:
        prepared = []
        for document in documents:
            metadata = dict(document.metadata)
            if metadata.get("tenant_id") is not None and str(metadata["tenant_id"]) != str(tenant_id):
                raise ValueError("Corpus document tenant does not match its write scope")
            metadata["tenant_id"] = str(tenant_id)
            prepared.append(self._prepare_retrieval_document(document.model_copy(update={"metadata": metadata})))
        if db is not None and prepared:
            document_ids = {UUID(str(document.metadata["document_id"])) for document in prepared}
            rows = (
                db.query(DBDocument.id, DBDocument.dataset_id)
                .filter(DBDocument.tenant_id == tenant_id, DBDocument.id.in_(document_ids))
                .all()
            )
            datasets = {
                str(document_id): str(dataset_id) if dataset_id is not None else "" for document_id, dataset_id in rows
            }
            for document in prepared:
                document_id = str(document.metadata["document_id"])
                if document_id not in datasets:
                    raise ValueError("Corpus document does not exist in its tenant write scope")
                document.metadata["dataset_id"] = datasets[document_id]
        if settings.VECTOR_BACKEND.strip().lower() == "milvus":
            self._store.upsert(prepared, tenant_id=tenant_id)
        self._invalidate_derived_indexes(tenant_id)

    def remove(self, *, tenant_id: UUID, metadata_filter: dict[str, Any]) -> int:
        if tenant_id is None:
            raise ValueError("Corpus deletion requires an explicit tenant")
        if not metadata_filter:
            raise ValueError("Corpus deletion requires a nonempty metadata filter")
        removed = (
            self._store.delete(tenant_id=tenant_id, metadata_filter=metadata_filter)
            if settings.VECTOR_BACKEND.strip().lower() == "milvus"
            else 0
        )
        self._invalidate_derived_indexes(tenant_id)
        return removed

    def _invalidate_derived_indexes(self, tenant_id: UUID) -> None:
        prefix = str(tenant_id)
        sparse, colbert = self.artifacts.sparse, self.artifacts.colbert
        for key in list(sparse._sparse_doc_vectors):
            if key == prefix or key.startswith(prefix + ":"):
                sparse.clear_scope(key)
        for key in list(colbert._colbert_index_cache):
            if key == prefix or key.startswith(prefix + ":"):
                colbert.clear_scope(key)
        with self._lock:
            for key in [key for key in self._corpus_token_cache if key[0] == prefix]:
                self._corpus_token_cache.pop(key, None)

    def clear_derived_index_caches(self) -> None:
        """Clear only derived artifacts and version tokens; native data is durable."""
        with self._lock:
            self._corpus_token_cache.clear()
        self.artifacts.sparse.clear()
        self.artifacts.colbert.clear()

    def load_corpus_snapshot(self, scope: CorpusScope) -> CorpusSnapshot:
        """Read a bounded published snapshot only for selected derived indexes."""
        db = self._open_session()
        try:
            documents = self._load_bounded_corpus_documents(
                db, tenant_id=scope.tenant_id, dataset_ids=scope.dataset_ids, document_ids=list(scope.document_ids)
            )
        finally:
            db.close()
        return CorpusSnapshot(scope, self.scope_key(scope), tuple(documents))

    def chunk_id_lookup(self, scope: CorpusScope, *, candidates: list[dict[str, Any]]) -> dict[str, str]:
        """Resolve only legacy vector hits lacking IDs, never the full corpus."""
        pairs = set()
        for item in candidates:
            metadata = item.get("metadata") or {}
            if item.get("chunk_id") or metadata.get("chunk_id"):
                continue
            document, index = metadata.get("document_id"), metadata.get("chunk_index")
            if document is not None and index is not None:
                pairs.add((UUID(str(document)), int(index)))
        if not pairs:
            return {}
        db = self._open_session()
        try:
            query = self._base_completed_chunk_query(db, scope.tenant_id).filter(
                tuple_(DocumentChunk.document_id, DocumentChunk.chunk_index).in_(list(pairs))
            )
            if scope.dataset_ids:
                query = query.filter(DBDocument.dataset_id.in_(scope.dataset_ids))
            if scope.document_ids:
                query = query.filter(DocumentChunk.document_id.in_(scope.document_ids))
            lookup = {}
            for row in self._iter_query_rows(query, batch_size=200):
                document = self._document_from_chunk_row(row)
                metadata = document.metadata
                lookup[f"{metadata['document_id']}:{metadata['chunk_index']}"] = str(document.id)
                if metadata.get("doc_pipeline_key"):
                    lookup[f"{metadata['doc_pipeline_key']}:{metadata['chunk_index']}"] = str(document.id)
            return lookup
        finally:
            db.close()

    @staticmethod
    def _iter_query_rows(query: Any, batch_size: int):
        return query.yield_per(batch_size)

    @staticmethod
    def _base_completed_chunk_query(db: Session, tenant_uuid: UUID):
        active_hash = func.coalesce(
            func.nullif(DBDocument.doc_metadata["active_pipeline_hash"].as_string(), ""),
            DBDocument.doc_metadata["pipeline_hash"].as_string(),
            "",
        )
        chunk_hash = func.coalesce(
            func.nullif(DocumentChunk.doc_metadata["pipeline_hash"].as_string(), ""),
            func.substr(DocumentChunk.doc_metadata["doc_pipeline_key"].as_string(), 38),
            "",
        )
        return (
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
            .filter(
                DBDocument.status == "completed",
                DBDocument.publication_status == "published",
                DBDocument.tenant_id == tenant_uuid,
                DocumentChunk.tenant_id == tenant_uuid,
                DBDocument.archived_at.is_(None),
                DBDocument.disabled_at.is_(None),
                DocumentChunk.disabled_at.is_(None),
                or_(active_hash == "", chunk_hash == "", chunk_hash == active_hash),
            )
            .enable_eagerloads(False)
            .execution_options(stream_results=True)
        )

    @staticmethod
    def _document_from_chunk_row(row: Any) -> Document:
        chunk, content, metadata, tenant, document, index, page, dataset = row
        normalized = {
            **(metadata or {}),
            "chunk_id": str(chunk),
            "tenant_id": str(tenant),
            "document_id": str(document),
            "dataset_id": str(dataset) if dataset is not None else None,
            "chunk_index": index,
        }
        normalized.setdefault("source", "unknown")
        if page is not None:
            normalized.setdefault("page", page)
        return Document(id=str(chunk), page_content=content, metadata=normalized)

    def _load_retrieval_docs_from_db(
        self,
        db: Session,
        *,
        tenant_id: UUID,
        dataset_id: UUID | None = None,
        dataset_ids=(),
        document_ids: list[UUID] | None = None,
        max_chunks: int = 0,
        batch_size: int = 2000,
    ) -> list[Document]:
        query = self._base_completed_chunk_query(db, tenant_id)
        if dataset_id is not None:
            query = query.filter(DBDocument.dataset_id == dataset_id)
        if dataset_ids:
            query = query.filter(DBDocument.dataset_id.in_(list(dataset_ids)))
        if document_ids:
            query = query.filter(DocumentChunk.document_id.in_(document_ids))
        query = query.order_by(DocumentChunk.document_id.asc(), DocumentChunk.chunk_index.asc())
        if max_chunks > 0:
            query = query.limit(max_chunks)
        return [
            self._prepare_retrieval_document(self._document_from_chunk_row(row))
            for row in self._iter_query_rows(query, batch_size)
        ]

    def resolve_version(self, scope: CorpusScope, *, db: Session | None = None) -> str | None:
        dataset_ids = self._normalize_dataset_scope_ids(scope.dataset_ids)
        scope_key = (str(scope.tenant_id), tuple(map(str, dataset_ids)), tuple(sorted(map(str, scope.document_ids))))
        if db is None:
            with self._lock:
                cached = self._corpus_token_cache.get(scope_key)
                if cached is not None and time.monotonic() - cached[0] <= 1.0:
                    self._corpus_token_cache.move_to_end(scope_key)
                    return cached[1]
        own_session = db is None
        current_db = self._open_session() if own_session else db
        try:
            token = corpus_cache_tokens.resolve_corpus_cache_token(
                current_db,
                tenant_id=scope.tenant_id,
                dataset_id=dataset_ids[0] if len(dataset_ids) == 1 else None,
                dataset_ids=dataset_ids if len(dataset_ids) > 1 else (),
                document_ids=scope.document_ids,
            )
            # Caller sessions may contain uncommitted writes; keep their versions out of the shared read cache.
            if token and own_session:
                with self._lock:
                    self._corpus_token_cache[scope_key] = (time.monotonic(), token)
                    while len(self._corpus_token_cache) > 128:
                        self._corpus_token_cache.popitem(last=False)
            return token
        except Exception as exc:
            _log_retriever_fallback("resolve_corpus_version", exc)
            return None
        finally:
            if own_session:
                current_db.close()

    def _count_retrieval_docs_in_db(
        self,
        db: Session,
        *,
        tenant_id: UUID,
        dataset_id: UUID | None = None,
        document_ids: list[UUID] | None = None,
        dataset_ids=(),
    ) -> int:
        query = self._base_completed_chunk_query(db, tenant_id).with_entities(func.count(DocumentChunk.id))
        if dataset_id is not None:
            query = query.filter(DBDocument.dataset_id == dataset_id)
        if dataset_ids:
            query = query.filter(DBDocument.dataset_id.in_(list(dataset_ids)))
        if document_ids:
            query = query.filter(DocumentChunk.document_id.in_(document_ids))
        return int(query.scalar() or 0)

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
            f"Retrieval rebuild aborted: scope has {int(chunk_count)} published chunks, exceeds RETRIEVAL_REBUILD_MAX_CHUNKS={int(limit)} (tenant_id={tenant_id}, dataset_id={dataset_id}, document_ids={len((document_ids if document_ids is not None else []))}). Narrow the rebuild scope or raise RETRIEVAL_REBUILD_MAX_CHUNKS."
        )

    def _load_bounded_corpus_documents(
        self,
        db: Session,
        *,
        tenant_id: UUID,
        dataset_id: UUID | None = None,
        document_ids: list[UUID] | None = None,
        batch_size: int = 2000,
        dataset_ids=(),
    ) -> list[Document]:
        """Load published corpus documents within the configured rebuild/snapshot cap."""
        rebuild_limit = max(0, settings.RETRIEVAL_REBUILD_MAX_CHUNKS)
        if rebuild_limit > 0:
            scope_count = self._count_retrieval_docs_in_db(
                db, tenant_id=tenant_id, dataset_id=dataset_id, document_ids=document_ids, dataset_ids=dataset_ids
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
            dataset_ids=dataset_ids,
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

    def rebuild(self, db: Session, *, scope: CorpusScope, batch_size: int = 2000) -> int:
        if not is_milvus_bm25_enabled():
            raise ValueError("BM25 backfill requires Milvus and BM25_INDEX_ENABLED=true")
        if batch_size <= 0:
            raise ValueError("BM25 backfill batch size must be positive")
        documents = self._load_bounded_corpus_documents(
            db,
            tenant_id=scope.tenant_id,
            dataset_ids=scope.dataset_ids,
            document_ids=list(scope.document_ids),
            batch_size=batch_size,
        )
        if not documents:
            self._store.initialize()
        for start in range(0, len(documents), batch_size):
            self._store.upsert(documents[start : start + batch_size], tenant_id=scope.tenant_id)
        corpus_cache_tokens.invalidate_corpus_cache_scope(
            db, tenant_id=scope.tenant_id, dataset_ids=scope.dataset_ids, document_ids=scope.document_ids
        )
        self._invalidate_derived_indexes(scope.tenant_id)
        return len(documents)

    def rebuild_bm25_index_for_operational_scope(
        self,
        db: Session,
        *,
        tenant_id: UUID,
        dataset_id: UUID | None = None,
        document_ids: list[UUID] | None = None,
        batch_size: int = 2000,
    ) -> int:
        return self.rebuild(
            db,
            scope=CorpusScope(
                tenant_id,
                (dataset_id,) if dataset_id is not None else (),
                tuple((document_ids if document_ids is not None else ())),
            ),
            batch_size=batch_size,
        )

    def rebuild_persisted_retrieval_indexes(
        self, db: Session, *, tenant_id: UUID, dataset_id: UUID | None = None, batch_size: int = 2000
    ) -> dict[str, Any]:
        if batch_size <= 0:
            raise ValueError("Retrieval backfill batch size must be positive")
        scope = CorpusScope(tenant_id, (dataset_id,) if dataset_id is not None else ())
        documents = self._load_bounded_corpus_documents(
            db, tenant_id=tenant_id, dataset_id=dataset_id, batch_size=batch_size
        )
        key = self.scope_key(scope)
        native = is_milvus_bm25_enabled()
        if native:
            if not documents:
                self._store.initialize()
            for start in range(0, len(documents), batch_size):
                self._store.upsert(documents[start : start + batch_size], tenant_id=tenant_id)
            corpus_cache_tokens.invalidate_corpus_cache_scope(db, tenant_id=tenant_id, dataset_ids=scope.dataset_ids)
            self._invalidate_derived_indexes(tenant_id)
        if settings.SPARSE_RETRIEVAL_ENABLED and documents:
            self.artifacts.sparse._build_sparse_index(
                cache_key=key,
                docs=documents,
                version_token=self.resolve_version(scope, db=db),
                provider=settings.SPARSE_RETRIEVAL_PROVIDER,
            )
        if settings.COLBERT_RETRIEVAL_ENABLED and documents:
            self.artifacts.colbert._build_colbert_index(cache_key=key, docs=documents)
        return {
            "tenant_id": str(tenant_id),
            "dataset_id": str(dataset_id) if dataset_id is not None else None,
            "cache_key": key,
            "doc_count": len(documents),
            "bm25_rebuilt": native,
            "sparse_rebuilt": settings.SPARSE_RETRIEVAL_ENABLED and bool(documents),
            "colbert_rebuilt": settings.COLBERT_RETRIEVAL_ENABLED and bool(documents),
        }


_shared_corpus_index = CorpusIndex()


def get_corpus_index() -> CorpusIndex:
    return _shared_corpus_index

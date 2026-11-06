"""Retriever-facing access to the shared server-owned full-text index."""

from typing import Any
from uuid import UUID

from langchain_core.documents import Document
from sqlalchemy.orm import Session

from app.rag.preprocessing.tokenization import tokenize_for_bm25
from app.rag.retrieval.corpus_index import CorpusScope, get_corpus_index
from app.rag.retrieval.hybrid.metadata_scope import collect_dataset_scope


class Bm25IndexMixin:
    _bm25_tokenize = staticmethod(tokenize_for_bm25)

    def upsert_bm25_documents(self, documents: list[Document], *, tenant_id: UUID, db: Session | None = None) -> None:
        get_corpus_index().upsert(db, tenant_id=tenant_id, documents=documents)

    def remove_document_from_bm25_index(self, document_id: UUID, *, tenant_id: UUID) -> int:
        return get_corpus_index().remove(tenant_id=tenant_id, metadata_filter={"document_id": str(document_id)})

    def remove_from_bm25_index_by_metadata_filter(self, *, tenant_id: UUID, metadata_filter: dict[str, Any]) -> int:
        return get_corpus_index().remove(tenant_id=tenant_id, metadata_filter=metadata_filter)

    def clear_bm25_cache(self) -> None:
        get_corpus_index().clear_bm25_cache()

    def rebuild_bm25_index_for_operational_scope(
        self,
        db: Session,
        *,
        tenant_id: UUID,
        dataset_id: UUID | None = None,
        document_ids: list[UUID] | None = None,
        batch_size: int = 2000,
    ) -> int:
        return get_corpus_index().rebuild_bm25_index_for_operational_scope(
            db, tenant_id=tenant_id, dataset_id=dataset_id, document_ids=document_ids, batch_size=batch_size
        )

    def rebuild_persisted_retrieval_indexes(
        self, db: Session, *, tenant_id: UUID, dataset_id: UUID | None = None, batch_size: int = 2000
    ) -> dict[str, Any]:
        return get_corpus_index().rebuild_persisted_retrieval_indexes(
            db, tenant_id=tenant_id, dataset_id=dataset_id, batch_size=batch_size
        )

    def _search_bm25(
        self,
        query: str,
        top_k: int = 10,
        document_ids: list[UUID] | None = None,
        tenant_id: UUID | None = None,
        metadata_filter: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        tenant = self._resolve_tenant_uuid(tenant_id)
        if tenant is None:
            raise ValueError("BM25 search requires an explicit tenant")
        datasets = tuple(collect_dataset_scope(metadata_filter)) or self._dataset_scope_ids(document_ids)
        result = get_corpus_index().search(
            query,
            scope=CorpusScope(tenant, datasets, tuple(document_ids or ())),
            top_k=top_k,
            metadata_filter=metadata_filter,
        )
        self._last_bm25_status = result.status
        return result.records

    def _bm25_scope_docs(
        self, *, tenant_id: UUID | None, document_ids: list[UUID] | None, metadata_filter: dict[str, Any] | None
    ):
        tenant = self._resolve_tenant_uuid(tenant_id)
        if tenant is None:
            raise ValueError("Derived corpus snapshots require an explicit tenant")
        datasets = tuple(collect_dataset_scope(metadata_filter)) or self._dataset_scope_ids(document_ids)
        snapshot = get_corpus_index().scope_documents(CorpusScope(tenant, datasets, tuple(document_ids or ())))
        return tenant, datasets, snapshot.cache_key, list(snapshot.documents)

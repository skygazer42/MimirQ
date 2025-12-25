from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from uuid import UUID

from langchain_core.documents import Document as LCDocument
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.document import DocumentChunk
from app.storage.search.hybrid_retriever import hybrid_retriever
from app.storage.vector.factory import get_vector_store


@dataclass(frozen=True)
class ChunkInput:
    content: str
    metadata: Dict[str, Any]
    page_number: Optional[int] = None
    start_char: Optional[int] = None
    end_char: Optional[int] = None


@dataclass(frozen=True)
class PersistChunksResult:
    db_chunks: List[DocumentChunk]
    chunk_ids: List[UUID]
    vector_ids: List[Optional[str]]
    total_characters: int


def _safe_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except Exception:
        return None


def _build_vector_docs(chunks: List[ChunkInput]) -> List[dict]:
    return [{"content": c.content, "metadata": c.metadata} for c in chunks]


def _index_vectors(
    docs: List[dict],
    *,
    document_id: UUID,
    tenant_id: UUID,
) -> List[Optional[str]]:
    if not docs:
        return []

    if not bool(getattr(settings, "CHUNK_VECTOR_ENABLED", True)):
        return [None] * len(docs)

    vector_store = get_vector_store()
    try:
        return list(vector_store.add_documents(docs, document_id, tenant_id))
    except Exception as exc:
        print(f"[WARN]  Failed to store vectors: {exc}")
        print("[WARN]  Proceeding without vector ids; BM25-only retrieval will still work.")
        return [None] * len(docs)


def persist_document_chunks(
    db: Session,
    *,
    document_id: UUID,
    tenant_id: UUID,
    chunks: List[ChunkInput],
    vector_ids: Optional[List[Optional[str]]] = None,
    commit: bool = True,
) -> List[DocumentChunk]:
    if not chunks:
        return []

    if vector_ids is None:
        vector_ids = [None] * len(chunks)
    if len(vector_ids) != len(chunks):
        raise ValueError(f"vector_ids length {len(vector_ids)} != chunks length {len(chunks)}")

    db_chunks: List[DocumentChunk] = []
    for idx, (chunk, vector_id) in enumerate(zip(chunks, vector_ids)):
        meta = dict(chunk.metadata or {})
        page_number = _safe_int(chunk.page_number) if chunk.page_number is not None else _safe_int(meta.get("page") or meta.get("page_number"))
        start_char = _safe_int(chunk.start_char) if chunk.start_char is not None else _safe_int(meta.get("start_char"))
        end_char = _safe_int(chunk.end_char) if chunk.end_char is not None else _safe_int(meta.get("end_char"))

        db_chunks.append(
            DocumentChunk(
                tenant_id=tenant_id,
                document_id=document_id,
                chunk_index=idx,
                content=chunk.content,
                page_number=page_number,
                start_char=start_char,
                end_char=end_char,
                doc_metadata=meta,
                vector_id=vector_id,
            )
        )

    db.add_all(db_chunks)
    db.flush()  # populate ids
    if commit:
        db.commit()

    return db_chunks


def update_bm25_index_for_chunks(
    *,
    db_chunks: List[DocumentChunk],
    tenant_id: UUID,
    document_id: UUID,
    default_source: str = "unknown",
) -> None:
    if not db_chunks:
        return
    if not bool(getattr(settings, "BM25_INDEX_ENABLED", True)):
        return

    bm25_docs: List[LCDocument] = []
    for db_chunk in db_chunks:
        meta = dict(db_chunk.doc_metadata or {})
        meta.setdefault("tenant_id", str(tenant_id))
        meta.setdefault("document_id", str(document_id))
        meta.setdefault("chunk_index", db_chunk.chunk_index)
        meta.setdefault("source", meta.get("source", default_source))
        meta.setdefault("page", db_chunk.page_number)
        meta.setdefault("image_id", meta.get("image_id"))
        meta.setdefault("image_url", meta.get("image_url"))
        bm25_docs.append(LCDocument(page_content=db_chunk.content, id=str(db_chunk.id), metadata=meta))

    hybrid_retriever.upsert_bm25_documents(bm25_docs, tenant_id=tenant_id)


def index_and_persist_chunks(
    db: Session,
    *,
    document_id: UUID,
    tenant_id: UUID,
    chunks: List[ChunkInput],
    default_source: str = "unknown",
    commit: bool = True,
) -> PersistChunksResult:
    """
    Unified chunk pipeline:
    1) vector index (optional)
    2) persist chunks to PostgreSQL
    3) update BM25 index (optional)
    """
    total_characters = sum(len(c.content or "") for c in chunks)
    vector_docs = _build_vector_docs(chunks)
    vector_ids = _index_vectors(vector_docs, document_id=document_id, tenant_id=tenant_id)
    db_chunks = persist_document_chunks(
        db,
        document_id=document_id,
        tenant_id=tenant_id,
        chunks=chunks,
        vector_ids=vector_ids,
        commit=commit,
    )

    try:
        update_bm25_index_for_chunks(
            db_chunks=db_chunks,
            tenant_id=tenant_id,
            document_id=document_id,
            default_source=default_source,
        )
    except Exception as exc:
        print(f"[WARN]  Failed to update BM25 index incrementally: {exc}")

    return PersistChunksResult(
        db_chunks=db_chunks,
        chunk_ids=[c.id for c in db_chunks],
        vector_ids=vector_ids,
        total_characters=total_characters,
    )

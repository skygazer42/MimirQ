from __future__ import annotations

from typing import List
from uuid import UUID

from sqlalchemy.orm import Session

from app.services.indexer import ChunkInput, IndexKind, IndexRecord, Indexer, PersistChunksResult


def index_and_persist_chunks(
    db: Session,
    *,
    document_id: UUID,
    tenant_id: UUID,
    chunks: List[ChunkInput],
    default_source: str = "unknown",
    commit: bool = True,
) -> PersistChunksResult:
    records = [
        IndexRecord(
            kind=IndexKind.CHUNK,
            content=c.content,
            metadata=c.metadata,
            document_id=document_id,
            page_number=c.page_number,
            start_char=c.start_char,
            end_char=c.end_char,
        )
        for c in chunks
    ]
    result = Indexer(db).upsert(
        tenant_id=tenant_id,
        records=records,
        default_source=default_source,
        commit=commit,
    ).chunk_result
    if result is None:
        raise RuntimeError("Chunk indexing returned no result")
    return result

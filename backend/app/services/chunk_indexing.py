from __future__ import annotations

from typing import List
from uuid import UUID

from sqlalchemy.orm import Session

from app.services.indexer import ChunkInput, IndexKind, Indexer, PersistChunksResult


def index_and_persist_chunks(
    db: Session,
    *,
    document_id: UUID,
    tenant_id: UUID,
    chunks: List[ChunkInput],
    default_source: str = "unknown",
    commit: bool = True,
) -> PersistChunksResult:
    return Indexer(db).index(
        IndexKind.CHUNK,
        document_id=document_id,
        tenant_id=tenant_id,
        chunks=chunks,
        default_source=default_source,
        commit=commit,
    )

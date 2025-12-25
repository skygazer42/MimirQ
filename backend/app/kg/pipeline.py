"""
Facade to run SAG extraction + search inside the existing backend.
SAG module can be toggled via settings.SAG_ENABLED.
"""
from typing import Dict, Iterable, List, Optional, Sequence
from uuid import UUID

from app.core.config import settings
from app.kg.engine import SAGEngine
from app.models.document import DocumentChunk
from app.services.indexer import IndexingOptions

_engine = None


def _load_engine() -> SAGEngine:
    global _engine
    if _engine is not None:
        return _engine
    if not settings.SAG_ENABLED:
        raise RuntimeError("SAG plugin is disabled. Set SAG_ENABLED=true to enable.")
    _engine = SAGEngine()
    return _engine


async def extract_events(
    chunk_ids: Iterable[UUID],
    tenant_id: Optional[UUID] = None,
    *,
    chunks: Optional[Sequence[DocumentChunk]] = None,
    index_options: Optional[IndexingOptions] = None,
):
    engine = _load_engine()
    return await engine.extract(
        chunk_ids,
        tenant_id=tenant_id,
        chunks=chunks,
        index_options=index_options,
    )


async def sag_search(
    query: str,
    tenant_id: Optional[UUID] = None,
    document_ids: Optional[List[UUID]] = None,
) -> Dict:
    engine = _load_engine()
    return await engine.search(query=query, tenant_id=tenant_id, document_ids=document_ids)

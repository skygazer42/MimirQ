"""
Facade to run KG extraction + search inside the existing backend.
KG module can be toggled via settings.KG_ENABLED (env: KG_ENABLED).
"""
from typing import Dict, Iterable, List, Optional, Sequence
from uuid import UUID

from app.core.config import settings
from app.rag.kg.engine import KGEngine
from app.models.document import DocumentChunk
from app.types.indexing import IndexingOptions

_engine = None


def _load_engine() -> KGEngine:
    global _engine
    if _engine is not None:
        return _engine
    if not settings.KG_ENABLED:
        raise RuntimeError("KG plugin is disabled. Set KG_ENABLED=true to enable.")
    _engine = KGEngine()
    return _engine


async def extract_events(
    chunk_ids: Iterable[UUID],
    tenant_id: Optional[UUID] = None,
    *,
    chunks: Optional[Sequence[DocumentChunk]] = None,
    index_options: Optional[IndexingOptions] = None,
    prompt_template_id: Optional[UUID] = None,
    prompt_template_key: Optional[str] = None,
    prompt_ab_experiment_key: Optional[str] = None,
    ab_user_key: Optional[str] = None,
    replace_existing: Optional[bool] = None,
    prune_orphan_entities: Optional[bool] = None,
):
    engine = _load_engine()
    return await engine.extract(
        chunk_ids,
        tenant_id=tenant_id,
        chunks=chunks,
        index_options=index_options,
        prompt_template_id=prompt_template_id,
        prompt_template_key=prompt_template_key,
        prompt_ab_experiment_key=prompt_ab_experiment_key,
        ab_user_key=ab_user_key,
        replace_existing=replace_existing,
        prune_orphan_entities=prune_orphan_entities,
    )


async def kg_search(
    query: str,
    tenant_id: Optional[UUID] = None,
    document_ids: Optional[List[UUID]] = None,
) -> Dict:
    engine = _load_engine()
    return await engine.search(query=query, tenant_id=tenant_id, document_ids=document_ids)

"""
Facade to run SAG extraction + search inside the existing backend.
SAG runs as a plugin under backend/third_party/sag and can be toggled via settings.SAG_ENABLED.
"""
from typing import Dict, Iterable, List, Optional
from uuid import UUID
import importlib

from app.core.config import settings

_engine = None


def _load_engine():
    global _engine
    if _engine is not None:
        return _engine
    if not settings.SAG_ENABLED:
        raise RuntimeError("SAG plugin is disabled. Set SAG_ENABLED=true to enable.")
    # dynamic import from third_party.sag
    engine_module = importlib.import_module("third_party.sag.engine.core")
    engine_cls = getattr(engine_module, "SAGEngine")
    _engine = engine_cls()
    return _engine


async def extract_events(chunk_ids: Iterable[UUID], tenant_id: Optional[UUID] = None):
    engine = _load_engine()
    return await engine.extract(chunk_ids, tenant_id=tenant_id)


async def sag_search(
    query: str,
    tenant_id: Optional[UUID] = None,
    document_ids: Optional[List[UUID]] = None,
) -> Dict:
    engine = _load_engine()
    return await engine.search(query=query, tenant_id=tenant_id, document_ids=document_ids)

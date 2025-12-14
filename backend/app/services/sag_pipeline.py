"""
Facade to run SAG extraction + search inside the existing backend.
"""
from typing import Dict, Iterable, Optional
from uuid import UUID

from app.sag.engine.core import SAGEngine


_engine: SAGEngine | None = None


def get_engine() -> SAGEngine:
    global _engine
    if _engine is None:
        _engine = SAGEngine()
    return _engine


async def extract_events(chunk_ids: Iterable[UUID], tenant_id: Optional[UUID] = None):
    engine = get_engine()
    return await engine.extract(chunk_ids, tenant_id=tenant_id)


async def sag_search(query: str, tenant_id: Optional[UUID] = None) -> Dict:
    engine = get_engine()
    return await engine.search(query=query, tenant_id=tenant_id)


"""
Knowledge Graph (KG) module.

Provides entity and event storage, retrieval, and search capabilities
for knowledge graph operations.
"""
from __future__ import annotations

from typing import Any

from app.kg.models import SagEntity, SagEventEntity, SagSourceEvent

__all__ = ["SagEntity", "SagSourceEvent", "SagEventEntity", "EntityRepository", "EventRepository", "get_session"]


def __getattr__(name: str) -> Any:  # pragma: no cover
    """
    Keep package import side-effects minimal to avoid circular imports.

    Prefer importing submodules directly:
    - from app.kg.repository import EntityRepository, EventRepository, get_session
    - from app.kg.utils import get_logger, ...
    - from app.kg.schemas import ...
    - from app.kg.pipeline import ...
    """
    if name in {"EntityRepository", "EventRepository", "get_session"}:
        from app.kg.repository import EntityRepository, EventRepository, get_session

        return {"EntityRepository": EntityRepository, "EventRepository": EventRepository, "get_session": get_session}[name]
    raise AttributeError(f"module 'app.kg' has no attribute {name!r}")

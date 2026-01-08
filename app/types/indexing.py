"""
Internal type definitions for indexing/ingestion pipeline (not API Schema)

Notes:
- These dataclasses/Enums are used by internal modules like services/rag/parsing
- To avoid triggering ORM/Settings initialization at import time, ORM models are not directly imported at runtime
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:  # pragma: no cover
    from app.models.document import DocumentChunk
    from app.rag.kg.models import KgEntity, KgSourceEvent


class IndexKind(str, Enum):
    CHUNK = "chunk"
    EVENT = "event"


@dataclass(frozen=True)
class IndexScope:
    tenant_id: UUID
    document_id: Optional[UUID] = None
    document_ids: Optional[List[UUID]] = None


@dataclass(frozen=True)
class IndexingOptions:
    chunk_vector_enabled: Optional[bool] = None
    bm25_index_enabled: Optional[bool] = None
    event_vector_enabled: Optional[bool] = None
    entity_vector_enabled: Optional[bool] = None


@dataclass(frozen=True)
class ChunkInput:
    content: str
    metadata: Dict[str, Any]
    page_number: Optional[int] = None
    start_char: Optional[int] = None
    end_char: Optional[int] = None


@dataclass(frozen=True)
class PersistChunksResult:
    db_chunks: List["DocumentChunk"]
    chunk_ids: List[UUID]
    vector_ids: List[Optional[str]]
    total_characters: int


@dataclass(frozen=True)
class EventEntityInput:
    name: str
    normalized_name: str
    type: str
    description: Optional[str] = None
    vector: Optional[List[float]] = None
    role: Optional[str] = None


@dataclass(frozen=True)
class EventInput:
    title: str
    summary: str
    content: str
    document_id: Optional[UUID]
    chunk_id: Optional[UUID]
    references: Optional[Dict[str, Any]] = None
    extra_data: Optional[Dict[str, Any]] = None
    vector: Optional[List[float]] = None
    entities: List[EventEntityInput] = field(default_factory=list)


@dataclass(frozen=True)
class IndexRecord:
    kind: IndexKind
    content: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    document_id: Optional[UUID] = None
    chunk_id: Optional[UUID] = None
    title: Optional[str] = None
    summary: Optional[str] = None
    references: Optional[Dict[str, Any]] = None
    extra_data: Optional[Dict[str, Any]] = None
    vector: Optional[List[float]] = None
    entities: List[EventEntityInput] = field(default_factory=list)
    page_number: Optional[int] = None
    start_char: Optional[int] = None
    end_char: Optional[int] = None


@dataclass(frozen=True)
class PersistEventsResult:
    events: List["KgSourceEvent"]
    entities: List["KgEntity"]
    event_ids: List[UUID]
    entity_ids: List[UUID]
    event_vector_ids: List[str]
    entity_vector_ids: List[str]


@dataclass(frozen=True)
class IndexBatchResult:
    chunk_result: Optional[PersistChunksResult] = None
    event_result: Optional[PersistEventsResult] = None


__all__ = [
    "ChunkInput",
    "EventEntityInput",
    "EventInput",
    "IndexBatchResult",
    "IndexKind",
    "IndexingOptions",
    "IndexRecord",
    "IndexScope",
    "PersistChunksResult",
    "PersistEventsResult",
]


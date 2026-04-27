"""
Internal type definitions for indexing/ingestion pipeline (not API Schema)

Notes:
- These dataclasses/Enums are used by internal modules like services/rag/parsing
- To avoid triggering ORM/Settings initialization at import time, ORM models are not directly imported at runtime
"""


from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any
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
    document_id: UUID | None = None
    document_ids: list[UUID] | None = None


@dataclass(frozen=True)
class IndexingOptions:
    chunk_vector_enabled: bool | None = None
    bm25_index_enabled: bool | None = None
    event_vector_enabled: bool | None = None
    entity_vector_enabled: bool | None = None
    # When enabled, prefix chunk content with lightweight context (e.g. header_path) before embedding.
    embedding_context_prefix_enabled: bool | None = None
    # When enabled, inject a short document/section-level context prefix before embedding (vector-only).
    # This is a deterministic heuristic by default; does not change stored chunk.content (DB).
    embedding_contextual_retrieval_enabled: bool | None = None
    # When enabled, contextual retrieval prefixes are only injected for chunks that carry
    # an explicit enrichment trigger (e.g. evidence_gap/contextual_enrichment_required).
    embedding_contextual_retrieval_lazy_mode: bool | None = None
    # When enabled, store extra field-aware embeddings (title/heading) alongside body embeddings.
    embedding_field_aware_enabled: bool | None = None


@dataclass(frozen=True)
class ChunkInput:
    content: str
    metadata: dict[str, Any]
    page_number: int | None = None
    start_char: int | None = None
    end_char: int | None = None


@dataclass(frozen=True)
class PersistChunksResult:
    db_chunks: list["DocumentChunk"]
    chunk_ids: list[UUID]
    vector_ids: list[str | None]
    total_characters: int


@dataclass(frozen=True)
class EventEntityInput:
    name: str
    normalized_name: str
    type: str
    description: str | None = None
    vector: list[float] | None = None
    role: str | None = None
    # Optional evidence grounding (best-effort; used for KG quality + debugging).
    evidence_quote: str | None = None
    evidence_source: str | None = None
    evidence_start_char: int | None = None
    evidence_end_char: int | None = None


@dataclass(frozen=True)
class EventInput:
    title: str
    summary: str
    content: str
    document_id: UUID | None
    chunk_id: UUID | None
    references: dict[str, Any] | None = None
    extra_data: dict[str, Any] | None = None
    vector: list[float] | None = None
    entities: list[EventEntityInput] = field(default_factory=list)


@dataclass(frozen=True)
class IndexRecord:
    kind: IndexKind
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)
    document_id: UUID | None = None
    chunk_id: UUID | None = None
    title: str | None = None
    summary: str | None = None
    references: dict[str, Any] | None = None
    extra_data: dict[str, Any] | None = None
    vector: list[float] | None = None
    entities: list[EventEntityInput] = field(default_factory=list)
    page_number: int | None = None
    start_char: int | None = None
    end_char: int | None = None


@dataclass(frozen=True)
class PersistEventsResult:
    events: list["KgSourceEvent"]
    entities: list["KgEntity"]
    event_ids: list[UUID]
    entity_ids: list[UUID]
    event_vector_ids: list[str]
    entity_vector_ids: list[str]


@dataclass(frozen=True)
class IndexBatchResult:
    chunk_result: PersistChunksResult | None = None
    event_result: PersistEventsResult | None = None


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

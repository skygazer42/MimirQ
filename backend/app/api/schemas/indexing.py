"""
索引相关的数据模型定义

包含索引操作所需的数据类、枚举等类型定义。
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import UUID

from app.models.document import DocumentChunk
from app.rag.kg.models import KgEntity, KgSourceEvent


class IndexKind(str, Enum):
    """索引类型枚举"""
    CHUNK = "chunk"
    EVENT = "event"


@dataclass(frozen=True)
class IndexScope:
    """索引范围"""
    tenant_id: UUID
    document_id: Optional[UUID] = None
    document_ids: Optional[List[UUID]] = None


@dataclass(frozen=True)
class IndexingOptions:
    """索引选项配置"""
    chunk_vector_enabled: Optional[bool] = None
    bm25_index_enabled: Optional[bool] = None
    event_vector_enabled: Optional[bool] = None
    entity_vector_enabled: Optional[bool] = None


@dataclass(frozen=True)
class ChunkInput:
    """分块输入数据"""
    content: str
    metadata: Dict[str, Any]
    page_number: Optional[int] = None
    start_char: Optional[int] = None
    end_char: Optional[int] = None


@dataclass(frozen=True)
class PersistChunksResult:
    """持久化分块结果"""
    db_chunks: List[DocumentChunk]
    chunk_ids: List[UUID]
    vector_ids: List[Optional[str]]
    total_characters: int


@dataclass(frozen=True)
class EventEntityInput:
    """事件实体输入数据"""
    name: str
    normalized_name: str
    type: str
    description: Optional[str] = None
    vector: Optional[List[float]] = None
    role: Optional[str] = None


@dataclass(frozen=True)
class EventInput:
    """事件输入数据"""
    title: str
    summary: str
    content: str
    document_id: Optional[UUID]
    chunk_id: Optional[UUID]
    references: Optional[Dict[str, Any]] = None
    vector: Optional[List[float]] = None
    entities: List[EventEntityInput] = field(default_factory=list)


@dataclass(frozen=True)
class IndexRecord:
    """索引记录"""
    kind: IndexKind
    content: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    document_id: Optional[UUID] = None
    chunk_id: Optional[UUID] = None
    title: Optional[str] = None
    summary: Optional[str] = None
    references: Optional[Dict[str, Any]] = None
    vector: Optional[List[float]] = None
    entities: List[EventEntityInput] = field(default_factory=list)
    page_number: Optional[int] = None
    start_char: Optional[int] = None
    end_char: Optional[int] = None


@dataclass(frozen=True)
class PersistEventsResult:
    """持久化事件结果"""
    events: List[KgSourceEvent]
    entities: List[KgEntity]
    event_ids: List[UUID]
    entity_ids: List[UUID]
    event_vector_ids: List[str]
    entity_vector_ids: List[str]


@dataclass(frozen=True)
class IndexBatchResult:
    """批量索引结果"""
    chunk_result: Optional[PersistChunksResult] = None
    event_result: Optional[PersistEventsResult] = None





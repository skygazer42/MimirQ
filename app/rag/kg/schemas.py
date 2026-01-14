from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class KGBaseModel(BaseModel):
    """BaseModel with orm_mode enabled for compatibility."""

    model_config = ConfigDict(from_attributes=True)


class KGExtractResponse(BaseModel):
    """Response after triggering KG extraction for a document."""

    document_id: UUID
    chunk_count: int
    event_count: int
    message: str = "KG extraction completed"


class KGSearchRequest(BaseModel):
    """KG search request."""

    query: str = Field(..., min_length=1, max_length=2048, description="Natural language query")
    tenant_id: Optional[UUID] = None
    document_ids: Optional[List[UUID]] = Field(default=None, max_length=500)


class KGSearchResponse(BaseModel):
    """KG search raw result passthrough."""

    result: Dict[str, Any]
    query: str


class KGGraphNode(BaseModel):
    """Graph node for frontend visualization."""

    id: str
    label: str
    group: int = 0
    val: int = 1
    meta: Dict[str, Any] = Field(default_factory=dict)


class KGGraphLink(BaseModel):
    """Graph link for frontend visualization."""

    source: str
    target: str
    label: str = ""
    weight: float = 1.0
    meta: Dict[str, Any] = Field(default_factory=dict)


class KGGraphResponse(BaseModel):
    """KG graph response."""

    nodes: List[KGGraphNode]
    links: List[KGGraphLink]
    stats: Dict[str, Any] = Field(default_factory=dict)


class KGEntityItem(KGBaseModel):
    """Entity details for API responses."""

    id: UUID
    name: str
    type: str
    normalized_name: str
    description: Optional[str] = None
    extra_data: Dict[str, Any] = Field(default_factory=dict)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    @field_validator("extra_data", mode="before")
    @classmethod
    def _coerce_extra_data(cls, v: Any) -> Dict[str, Any]:  # noqa: ANN401
        return v or {}


class KGEventItem(KGBaseModel):
    """Event details for API responses."""

    id: UUID
    title: str
    summary: str
    content: str
    document_id: Optional[UUID] = None
    chunk_id: Optional[UUID] = None
    references: Dict[str, Any] = Field(default_factory=dict)
    extra_data: Dict[str, Any] = Field(default_factory=dict)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    @field_validator("references", "extra_data", mode="before")
    @classmethod
    def _coerce_dict_fields(cls, v: Any) -> Dict[str, Any]:  # noqa: ANN401
        return v or {}


class KGEventEntityItem(KGBaseModel):
    """Event-entity relation details."""

    entity: KGEntityItem
    weight: float = 1.0
    role: Optional[str] = None


class KGEventDetailResponse(BaseModel):
    event: KGEventItem
    entities: List[KGEventEntityItem] = Field(default_factory=list)


class KGEntityNeighbor(BaseModel):
    entity_id: UUID
    name: str
    type: str
    count: int


class KGEntityDetailResponse(BaseModel):
    entity: KGEntityItem
    events: List[KGEventItem] = Field(default_factory=list)
    neighbors: List[KGEntityNeighbor] = Field(default_factory=list)
    stats: Dict[str, Any] = Field(default_factory=dict)


class KGEntityTypeCount(BaseModel):
    type: str
    count: int


class KGStatsResponse(BaseModel):
    events: int
    entities: int
    links: int
    entity_types: List[KGEntityTypeCount] = Field(default_factory=list)
    updated_at: Optional[datetime] = None


class KGDeleteResponse(BaseModel):
    document_id: UUID
    events_deleted: int = 0
    entities_pruned: int = 0

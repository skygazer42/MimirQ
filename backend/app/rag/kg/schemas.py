from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


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

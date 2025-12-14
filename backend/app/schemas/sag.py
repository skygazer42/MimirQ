from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class SAGExtractResponse(BaseModel):
    """Response after triggering SAG extraction for a document."""

    document_id: UUID
    chunk_count: int
    event_count: int
    message: str = "SAG extraction completed"


class SAGSearchRequest(BaseModel):
    """SAG search request."""

    query: str = Field(..., min_length=1, description="Natural language query")
    tenant_id: Optional[UUID] = None


class SAGSearchResponse(BaseModel):
    """SAG search raw result passthrough."""

    result: Dict[str, Any]
    query: str

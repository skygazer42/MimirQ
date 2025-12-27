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

    query: str = Field(..., min_length=1, description="Natural language query")
    tenant_id: Optional[UUID] = None
    document_ids: Optional[List[UUID]] = None


class KGSearchResponse(BaseModel):
    """KG search raw result passthrough."""

    result: Dict[str, Any]
    query: str


# Backward-compatible aliases (SAG -> KG)
SAGBaseModel = KGBaseModel
SAGExtractResponse = KGExtractResponse
SAGSearchRequest = KGSearchRequest
SAGSearchResponse = KGSearchResponse

"""
Ingestion run manifest schemas.

These schemas expose a unified run_id view for ingestion entrypoints.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class IngestionRunDocumentOut(BaseModel):
    document_id: UUID
    status: str
    source_ref: Optional[str] = None
    created_at: Optional[datetime] = None


class IngestionRunOut(BaseModel):
    id: UUID
    tenant_id: UUID
    dataset_id: Optional[UUID] = None
    kind: str
    requested_by: Optional[str] = None
    status: str
    config: Dict[str, Any] = Field(default_factory=dict)
    stats: Dict[str, Any] = Field(default_factory=dict)
    error_message: Optional[str] = None
    created_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    documents: List[IngestionRunDocumentOut] = Field(default_factory=list)


class IngestionRunListResponse(BaseModel):
    total: int
    items: List[IngestionRunOut] = Field(default_factory=list)


class IngestionRunCompareResponse(BaseModel):
    run_a: IngestionRunOut
    run_b: IngestionRunOut
    # Simple, UI-friendly diff payload (best-effort).
    diff: Dict[str, Any] = Field(default_factory=dict)

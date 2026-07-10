"""
Ingestion run manifest schemas.

These schemas expose a unified run_id view for ingestion entrypoints.
"""


from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class IngestionRunDocumentOut(BaseModel):
    document_id: UUID
    status: str
    source_ref: str | None = None
    created_at: datetime | None = None


class IngestionRunOut(BaseModel):
    id: UUID
    tenant_id: UUID
    dataset_id: UUID | None = None
    kind: str
    requested_by: str | None = None
    status: str
    config: dict[str, Any] = Field(default_factory=dict)
    stats: dict[str, Any] = Field(default_factory=dict)
    error_message: str | None = None
    created_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    documents: list[IngestionRunDocumentOut] = Field(default_factory=list)


class IngestionRunListResponse(BaseModel):
    total: int
    items: list[IngestionRunOut] = Field(default_factory=list)


class IngestionRunCompareResponse(BaseModel):
    run_a: IngestionRunOut
    run_b: IngestionRunOut
    # Simple, UI-friendly diff payload (best-effort).
    diff: dict[str, Any] = Field(default_factory=dict)

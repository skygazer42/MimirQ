"""
Connector-related Pydantic schemas.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from app.api.schemas.document import DocumentAccessUpdateRequest, DocumentPipelineOptions


ConnectorId = Literal["url_batch"]
ConnectorRunStatus = Literal["pending", "running", "completed", "failed", "cancelled"]


class ConnectorInfo(BaseModel):
    id: ConnectorId
    name: str
    description: str = ""
    supports_incremental: bool = False


class UrlBatchConnectorConfig(BaseModel):
    """Config for `url_batch` connector."""

    urls: List[str] = Field(..., min_length=1, max_length=50, description="One URL per entry")
    filename: Optional[str] = Field(
        default=None,
        max_length=500,
        description="Optional: override filename for display/extension inference (applies to all urls).",
    )
    parser_backend: str = Field(default="auto")
    chunk_strategy: str = Field(default="langchain_recursive")
    pipeline: Optional[DocumentPipelineOptions] = None
    access: Optional[DocumentAccessUpdateRequest] = None

    @model_validator(mode="after")
    def _normalize(self) -> "UrlBatchConnectorConfig":
        # Trim and dedupe URLs.
        seen: set[str] = set()
        normalized: list[str] = []
        for raw in self.urls or []:
            url = str(raw or "").strip()
            if not url or url in seen:
                continue
            seen.add(url)
            normalized.append(url)
            if len(normalized) >= 50:
                break
        self.urls = normalized
        return self


class ConnectorRunCreateRequest(BaseModel):
    connector_id: ConnectorId = "url_batch"
    dataset_id: Optional[UUID] = None
    config: UrlBatchConnectorConfig


class ConnectorRunDocumentOut(BaseModel):
    document_id: UUID
    source_ref: Optional[str] = None
    status: str = "created"


class ConnectorRunOut(BaseModel):
    id: UUID
    tenant_id: UUID
    dataset_id: Optional[UUID] = None
    connector_id: str
    requested_by: Optional[str] = None
    status: ConnectorRunStatus
    config: Dict[str, Any] = Field(default_factory=dict)
    stats: Dict[str, Any] = Field(default_factory=dict)
    error_message: Optional[str] = None
    task_id: Optional[str] = None
    created_at: datetime
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    documents: List[ConnectorRunDocumentOut] = Field(default_factory=list)


class ConnectorRunListResponse(BaseModel):
    total: int
    items: List[ConnectorRunOut]


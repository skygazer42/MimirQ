"""Report-related Pydantic schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field

from app.api.schemas.dataset_profile import DatasetProfileSummary


class PipelineVersionSummary(BaseModel):
    pipeline_hash: str
    documents: int = 0


class ComplianceSummary(BaseModel):
    """Lightweight compliance signals derived from governance/profile stats."""

    pii_hits_total: Dict[str, int] = Field(default_factory=dict)
    secrets_hits_total: Dict[str, int] = Field(default_factory=dict)
    quarantined_documents: int = 0
    failed_documents: int = 0


class ConnectorRunSummary(BaseModel):
    id: UUID
    connector_id: str
    status: str
    created_at: datetime
    finished_at: Optional[datetime] = None
    error_message: Optional[str] = None
    stats: Dict[str, Any] = Field(default_factory=dict)


class DatasetReportOut(BaseModel):
    dataset_id: UUID
    dataset_name: Optional[str] = None
    pipeline_hash: Optional[str] = None
    generated_at: datetime

    profile: DatasetProfileSummary
    compliance: ComplianceSummary
    pipeline_versions: List[PipelineVersionSummary] = Field(default_factory=list)
    connectors: List[ConnectorRunSummary] = Field(default_factory=list)

    # A snapshot of dataset-level config (best-effort), useful for sharing.
    dataset_metadata: Dict[str, Any] = Field(default_factory=dict)


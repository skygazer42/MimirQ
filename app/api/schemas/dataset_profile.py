"""
Dataset profile / scan schemas.

These schemas are used to:
- Return real-time dataset profiling summary (fast, computed on demand)
- Track deep scan runs (async backfill + persisted summary)
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class DatasetProfileHistogramBin(BaseModel):
    label: str
    min: Optional[int] = None
    max: Optional[int] = None
    count: int = 0


class DatasetProfilePercentiles(BaseModel):
    p25: int = 0
    p50: int = 0
    p75: int = 0
    p90: int = 0
    p99: int = 0


class DatasetProfilePdfScanStats(BaseModel):
    scanned: int = 0
    not_scanned: int = 0
    unknown: int = 0


class DatasetProfileFindingSummary(BaseModel):
    key: str
    label: str
    severity: Literal["info", "warning", "error"] = "info"
    count: int = 0
    description: Optional[str] = None


class DatasetProfileScanRunSummary(BaseModel):
    id: UUID
    kind: str = "deep"
    status: str = "pending"
    progress: int = 0
    requested_by: Optional[str] = None
    created_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    error_message: Optional[str] = None


class DatasetProfileSummary(BaseModel):
    dataset_id: UUID
    generated_at: datetime

    total_documents: int = 0
    total_size_bytes: int = 0
    by_status: Dict[str, int] = Field(default_factory=dict)
    by_file_type: Dict[str, int] = Field(default_factory=dict)

    file_size_histogram: List[DatasetProfileHistogramBin] = Field(default_factory=list)

    # Text length based on `total_characters` (best-effort).
    length_percentiles: DatasetProfilePercentiles = Field(default_factory=DatasetProfilePercentiles)
    length_histogram: List[DatasetProfileHistogramBin] = Field(default_factory=list)

    pdf_scan: DatasetProfilePdfScanStats = Field(default_factory=DatasetProfilePdfScanStats)

    pii_hits_total: Dict[str, int] = Field(default_factory=dict)
    secrets_hits_total: Dict[str, int] = Field(default_factory=dict)

    # Actionable buckets.
    findings: List[DatasetProfileFindingSummary] = Field(default_factory=list)

    # Best-effort last deep scan run metadata (may be None).
    latest_scan_run: Optional[DatasetProfileScanRunSummary] = None


class DatasetProfileDocumentOut(BaseModel):
    id: UUID
    dataset_id: Optional[UUID] = None
    filename: str
    file_type: str
    file_size: int
    status: str
    chunk_count: int = 0
    total_characters: int = 0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    error_message: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class DatasetProfileFindingListResponse(BaseModel):
    total: int
    items: List[DatasetProfileDocumentOut] = Field(default_factory=list)


class DatasetProfileScanRunCreateRequest(BaseModel):
    backfill_pdf_quality: bool = True
    backfill_text_quality: bool = True
    compute_file_hash: bool = False
    # Hard cap for safety; 0/None means no cap.
    max_documents: Optional[int] = Field(default=None, ge=0, le=1_000_000)


class DatasetProfileScanRunOut(BaseModel):
    id: UUID
    tenant_id: UUID
    dataset_id: UUID
    requested_by: Optional[str] = None
    kind: str
    status: str
    progress: int
    config: Dict[str, Any] = Field(default_factory=dict)
    summary: Dict[str, Any] = Field(default_factory=dict)
    error_message: Optional[str] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class DatasetProfileScanRunListResponse(BaseModel):
    total: int
    items: List[DatasetProfileScanRunOut] = Field(default_factory=list)

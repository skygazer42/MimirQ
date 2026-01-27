"""
Dataset precheck / scan schemas.

These schemas are used to:
- Track precheck scan runs over a local folder (before ingestion)
- Return summary statistics + actionable finding buckets
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class DatasetPrecheckHistogramBin(BaseModel):
    label: str
    min: Optional[int] = None
    max: Optional[int] = None
    count: int = 0


class DatasetPrecheckPercentiles(BaseModel):
    p25: int = 0
    p50: int = 0
    p75: int = 0
    p90: int = 0
    p99: int = 0


class DatasetPrecheckPdfScanStats(BaseModel):
    scanned: int = 0
    not_scanned: int = 0
    unknown: int = 0


class DatasetPrecheckFindingSummary(BaseModel):
    key: str
    label: str
    severity: Literal["info", "warning", "error"] = "info"
    count: int = 0
    description: Optional[str] = None


class DatasetPrecheckSummary(BaseModel):
    dataset_id: UUID
    scan_run_id: UUID
    generated_at: datetime

    total_files: int = 0
    total_size_bytes: int = 0
    by_file_type: Dict[str, int] = Field(default_factory=dict)

    file_size_histogram: List[DatasetPrecheckHistogramBin] = Field(default_factory=list)

    # Text length based on best-effort extracted characters.
    length_percentiles: DatasetPrecheckPercentiles = Field(default_factory=DatasetPrecheckPercentiles)
    length_histogram: List[DatasetPrecheckHistogramBin] = Field(default_factory=list)

    pdf_scan: DatasetPrecheckPdfScanStats = Field(default_factory=DatasetPrecheckPdfScanStats)

    pii_hits_total: Dict[str, int] = Field(default_factory=dict)
    secrets_hits_total: Dict[str, int] = Field(default_factory=dict)

    findings: List[DatasetPrecheckFindingSummary] = Field(default_factory=list)


class DatasetPrecheckFileOut(BaseModel):
    # Relative path (under root_path) by default; may be redacted/aliased by config.
    name: str
    file_type: str
    file_size: int
    text_characters: int = 0
    estimated_text: bool = False
    pdf_scanned: Optional[bool] = None
    pii_hits: Dict[str, int] = Field(default_factory=dict)
    secrets_hits: Dict[str, int] = Field(default_factory=dict)
    file_sha256: Optional[str] = None
    findings: List[str] = Field(default_factory=list)
    error_message: Optional[str] = None


class DatasetPrecheckFindingListResponse(BaseModel):
    total: int
    items: List[DatasetPrecheckFileOut] = Field(default_factory=list)


class DatasetPrecheckScanRunCreateRequest(BaseModel):
    # Local folder path. The backend must be allowed to access it (see LOCAL_SCAN_* settings).
    root_path: str = Field(min_length=1, max_length=4096)

    # Safety cap (0/None = no cap; still bounded by PRECHECK_SCAN_MAX_FILES).
    max_files: Optional[int] = Field(default=None, ge=0, le=1_000_000)

    # Feature toggles (keep defaults conservative).
    enable_pdf_quality: bool = True
    enable_text_extract: bool = True
    enable_pii: bool = False
    enable_secrets: bool = False
    compute_file_hash: bool = False

    # Optional overrides for extraction limits.
    pdf_sample_pages: Optional[int] = Field(default=None, ge=1, le=50)
    text_extract_max_bytes: Optional[int] = Field(default=None, ge=1_000, le=50_000_000)

    # Optional PDF page-type heuristics (used for scan_ratio/low_density_ratio metrics; best-effort).
    pdf_min_text_chars_per_page: Optional[int] = Field(default=None, ge=0, le=20_000)
    pdf_text_chars_per_page: Optional[int] = Field(default=None, ge=0, le=50_000)
    pdf_scan_ratio_threshold: Optional[float] = Field(default=None, ge=0.0, le=1.0)

    # Privacy: when enabled, API responses will not include real paths (only aliases).
    redact_paths: bool = False

    # Optional: include masked match samples (for internal review; off by default).
    enable_pii_samples: bool = False
    pii_context_chars: Optional[int] = Field(default=None, ge=0, le=500)
    pii_max_samples_per_file: Optional[int] = Field(default=None, ge=0, le=50)

    enable_secrets_samples: bool = False
    secrets_context_chars: Optional[int] = Field(default=None, ge=0, le=500)
    secrets_max_samples_per_file: Optional[int] = Field(default=None, ge=0, le=50)

    # Optional: near-duplicate candidate detection (SimHash on extracted text samples).
    enable_near_dup: bool = False
    near_dup_hamming_threshold: Optional[int] = Field(default=None, ge=0, le=32)
    near_dup_max_pairs: Optional[int] = Field(default=None, ge=0, le=100_000)

    # Optional: representative sampling (for pricing/POC). Writes a sample list into run artifacts.
    enable_sampling: bool = True
    sample_size: Optional[int] = Field(default=None, ge=0, le=2000)

    # Optional: incremental scan reuse (reuse unchanged file records from a previous run).
    reuse_unchanged_files: bool = False
    reuse_from_scan_run_id: Optional[UUID] = None


class DatasetPrecheckScanRunOut(BaseModel):
    id: UUID
    tenant_id: UUID
    dataset_id: UUID
    requested_by: Optional[str] = None
    kind: str
    status: str
    progress: int
    config: Dict[str, Any] = Field(default_factory=dict)
    summary: Dict[str, Any] = Field(default_factory=dict)
    artifacts: Dict[str, Any] = Field(default_factory=dict)
    error_message: Optional[str] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class DatasetPrecheckScanRunListResponse(BaseModel):
    total: int
    items: List[DatasetPrecheckScanRunOut] = Field(default_factory=list)

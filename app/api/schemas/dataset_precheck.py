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

from app.api.schemas.ingestion_policy import IngestionPolicy


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


class DatasetPrecheckPdfPageBreakdown(BaseModel):
    """
    Best-effort per-page type breakdown (computed on sampled pages).

    This is intended for *transparent* PDF routing decisions (scan/mixed/low-density),
    not as a strict ground truth.
    """

    page_count: int = 0
    sampled_pages: int = 0
    scanned_pages: int = 0
    text_pages: int = 0
    low_density_pages: int = 0
    unknown_pages: int = 0
    scan_ratio: float = 0.0
    low_density_ratio: float = 0.0


class DatasetPrecheckSpreadsheetStats(BaseModel):
    row_count: int = 0
    col_count: int = 0
    sheet_count: int = 0
    merged_cell_ratio: float = 0.0
    estimated_rows: bool = False
    estimated_cols: bool = False


class DatasetPrecheckMatchSample(BaseModel):
    kind: str
    masked: str
    context: str
    start: Optional[int] = None
    end: Optional[int] = None


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
    # How many records were reused from a previous scan run (incremental scans).
    reused_files: int = 0
    by_file_type: Dict[str, int] = Field(default_factory=dict)

    file_size_histogram: List[DatasetPrecheckHistogramBin] = Field(default_factory=list)

    # Text length based on best-effort extracted characters.
    length_percentiles: DatasetPrecheckPercentiles = Field(default_factory=DatasetPrecheckPercentiles)
    length_histogram: List[DatasetPrecheckHistogramBin] = Field(default_factory=list)

    # Token length based on best-effort extracted text (heuristic).
    token_percentiles: DatasetPrecheckPercentiles = Field(default_factory=DatasetPrecheckPercentiles)
    token_histogram: List[DatasetPrecheckHistogramBin] = Field(default_factory=list)

    pdf_scan: DatasetPrecheckPdfScanStats = Field(default_factory=DatasetPrecheckPdfScanStats)
    # Echo PDF page-type heuristics used during the scan (best-effort; for transparency).
    pdf_detection: Dict[str, Any] = Field(default_factory=dict)

    pii_hits_total: Dict[str, int] = Field(default_factory=dict)
    secrets_hits_total: Dict[str, int] = Field(default_factory=dict)

    findings: List[DatasetPrecheckFindingSummary] = Field(default_factory=list)


class DatasetPrecheckFileOut(BaseModel):
    # Relative path (under root_path) by default; may be redacted/aliased by config.
    name: str
    file_type: str
    file_size: int
    file_mtime: Optional[int] = None
    text_characters: int = 0
    # Best-effort token estimate derived from sampled extracted text (rough cost proxy).
    text_tokens_est: int = 0
    estimated_text: bool = False
    pdf_scanned: Optional[bool] = None
    pdf_pages: Optional[DatasetPrecheckPdfPageBreakdown] = None
    spreadsheet: Optional[DatasetPrecheckSpreadsheetStats] = None
    text_simhash64: Optional[str] = None
    pii_hits: Dict[str, int] = Field(default_factory=dict)
    secrets_hits: Dict[str, int] = Field(default_factory=dict)
    pii_samples: List[DatasetPrecheckMatchSample] = Field(default_factory=list)
    secrets_samples: List[DatasetPrecheckMatchSample] = Field(default_factory=list)
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


# ==================== Extras (samples / near-dup / diff / suggestions) ====================


class DatasetPrecheckSamplesResponse(BaseModel):
    """
    Representative samples payload for pricing/POC alignment.

    Note: Items reuse DatasetPrecheckFileOut (already redacted/aliased when redact_paths=true).
    """

    requested: int = 0
    strata_count: int = 0
    representative: List[DatasetPrecheckFileOut] = Field(default_factory=list)
    needs_review: Dict[str, List[DatasetPrecheckFileOut]] = Field(default_factory=dict)
    top_large_files: List[DatasetPrecheckFileOut] = Field(default_factory=list)
    top_long_text: List[DatasetPrecheckFileOut] = Field(default_factory=list)


class DatasetPrecheckNearDupCluster(BaseModel):
    id: str
    members: List[str] = Field(default_factory=list)


class DatasetPrecheckNearDupPair(BaseModel):
    a: str
    b: str
    distance: int


class DatasetPrecheckNearDupResponse(BaseModel):
    threshold: int = 0
    max_pairs: int = 0
    pairs_returned: int = 0
    clusters_returned: int = 0
    clusters: List[DatasetPrecheckNearDupCluster] = Field(default_factory=list)
    pairs: List[DatasetPrecheckNearDupPair] = Field(default_factory=list)


class DatasetPrecheckDiffItem(BaseModel):
    key: str
    before: int = 0
    after: int = 0
    delta: int = 0


class DatasetPrecheckDiffResponse(BaseModel):
    """
    Diff between two scan run summaries (objective numbers only).
    """

    base_scan_run_id: UUID
    target_scan_run_id: UUID
    generated_at: datetime

    total_files: DatasetPrecheckDiffItem
    total_size_bytes: DatasetPrecheckDiffItem
    pdf_scanned: DatasetPrecheckDiffItem
    pdf_unknown: DatasetPrecheckDiffItem

    by_file_type: List[DatasetPrecheckDiffItem] = Field(default_factory=list)
    findings: List[DatasetPrecheckDiffItem] = Field(default_factory=list)


class DatasetPrecheckManualReviewBucket(BaseModel):
    """
    A bounded list of file names that likely require manual review.
    """

    key: str
    total: int = 0
    sample_names: List[str] = Field(default_factory=list)


class DatasetPrecheckIngestionSuggestionResponse(BaseModel):
    """
    Suggested, importable ingestion policy + manual-review buckets derived from a precheck run.
    """

    generated_at: datetime
    policy: IngestionPolicy
    notes: List[str] = Field(default_factory=list)
    manual_review: List[DatasetPrecheckManualReviewBucket] = Field(default_factory=list)

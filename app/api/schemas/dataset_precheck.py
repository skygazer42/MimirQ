"""
Dataset precheck / scan schemas.

These schemas are used to:
- Track precheck scan runs over a local folder (before ingestion)
- Return summary statistics + actionable finding buckets
"""


from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.api.schemas.ingestion_policy import IngestionPolicy


class DatasetPrecheckHistogramBin(BaseModel):
    label: str
    min: int | None = None
    max: int | None = None
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


class DatasetPrecheckNearDupSummary(BaseModel):
    """
    Compact near-duplicate stats summary (for reports/dashboards).
    """

    enabled: bool = False
    threshold: int = 0
    pairs: int = 0
    clusters: int = 0
    affected_files: int = 0
    largest_cluster_size: int = 0
    keep_candidates_sample: list[str] = Field(default_factory=list)


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
    start: int | None = None
    end: int | None = None


class DatasetPrecheckFindingSummary(BaseModel):
    key: str
    label: str
    severity: Literal["info", "warning", "error"] = "info"
    count: int = 0
    description: str | None = None


class DatasetPrecheckFileTypeStat(BaseModel):
    file_type: str
    count: int = 0
    total_size_bytes: int = 0


class DatasetPrecheckDirectoryStat(BaseModel):
    """
    Directory-level aggregation over precheck file records (best-effort).

    Note: Only meaningful when scan paths are not redacted (redact_paths=false).
    """

    path: str
    total_files: int = 0
    total_size_bytes: int = 0
    risky_files: int = 0
    findings: dict[str, int] = Field(default_factory=dict)


class DatasetPrecheckSummary(BaseModel):
    dataset_id: UUID
    scan_run_id: UUID
    generated_at: datetime

    schema_id: str = "mimirq.dataset_precheck_summary.v3"
    schema_version: int = 3

    total_files: int = 0
    total_size_bytes: int = 0
    # How many records were reused from a previous scan run (incremental scans).
    reused_files: int = 0
    by_file_type: dict[str, int] = Field(default_factory=dict)
    # Total bytes by file type (extension).
    by_file_type_bytes: dict[str, int] = Field(default_factory=dict)
    # Convenient typed breakdown for UI/report rendering.
    file_type_stats: list[DatasetPrecheckFileTypeStat] = Field(default_factory=list)
    # Best-effort language/script mix from sampled extracted text.
    language_mix: dict[str, int] = Field(default_factory=dict)
    # Top directory aggregates (path prefix under scan root).
    directory_stats: list[DatasetPrecheckDirectoryStat] = Field(default_factory=list)

    file_size_histogram: list[DatasetPrecheckHistogramBin] = Field(default_factory=list)

    # Text length based on best-effort extracted characters.
    length_percentiles: DatasetPrecheckPercentiles = Field(default_factory=DatasetPrecheckPercentiles)
    length_histogram: list[DatasetPrecheckHistogramBin] = Field(default_factory=list)

    # Token length based on best-effort extracted text (heuristic).
    token_percentiles: DatasetPrecheckPercentiles = Field(default_factory=DatasetPrecheckPercentiles)
    token_histogram: list[DatasetPrecheckHistogramBin] = Field(default_factory=list)

    pdf_scan: DatasetPrecheckPdfScanStats = Field(default_factory=DatasetPrecheckPdfScanStats)
    # Echo PDF page-type heuristics used during the scan (best-effort; for transparency).
    pdf_detection: dict[str, Any] = Field(default_factory=dict)

    # Higher-level, explainable buckets for report dashboards.
    risk_buckets: dict[str, int] = Field(default_factory=dict)
    primary_tag_counts: dict[str, int] = Field(default_factory=dict)
    processing_path_counts: dict[str, int] = Field(default_factory=dict)
    # Compact near-dup summary (full artifact lives in near_dups.json).
    near_dup_summary: DatasetPrecheckNearDupSummary = Field(default_factory=DatasetPrecheckNearDupSummary)

    pii_hits_total: dict[str, int] = Field(default_factory=dict)
    secrets_hits_total: dict[str, int] = Field(default_factory=dict)

    findings: list[DatasetPrecheckFindingSummary] = Field(default_factory=list)


class DatasetPrecheckFileOut(BaseModel):
    # Relative path (under root_path) by default; may be redacted/aliased by config.
    name: str
    file_type: str
    file_size: int
    file_mtime: int | None = None
    text_characters: int = 0
    # Best-effort token estimate derived from sampled extracted text (rough cost proxy).
    text_tokens_est: int = 0
    # Best-effort language bucket from sampled extracted text.
    language: str | None = None
    language_confidence: float | None = None
    estimated_text: bool = False
    pdf_scanned: bool | None = None
    pdf_pages: DatasetPrecheckPdfPageBreakdown | None = None
    spreadsheet: DatasetPrecheckSpreadsheetStats | None = None
    text_simhash64: str | None = None
    pii_hits: dict[str, int] = Field(default_factory=dict)
    secrets_hits: dict[str, int] = Field(default_factory=dict)
    pii_samples: list[DatasetPrecheckMatchSample] = Field(default_factory=list)
    secrets_samples: list[DatasetPrecheckMatchSample] = Field(default_factory=list)
    file_sha256: str | None = None
    parse_failure_kind: str | None = None
    primary_tag: str | None = None
    processing_paths: list[str] = Field(default_factory=list)
    findings: list[str] = Field(default_factory=list)
    error_message: str | None = None
    review_disposition: Literal["approved", "manual"] | None = None
    reviewed_at: datetime | None = None
    reviewed_by: str | None = None


class DatasetPrecheckFindingListResponse(BaseModel):
    total: int
    items: list[DatasetPrecheckFileOut] = Field(default_factory=list)


class DatasetPrecheckScanRunCreateRequest(BaseModel):
    # Local folder path. The backend must be allowed to access it (see LOCAL_SCAN_* settings).
    root_path: str = Field(min_length=1, max_length=4096)

    # Safety cap (0/None = no cap; still bounded by PRECHECK_SCAN_MAX_FILES).
    max_files: int | None = Field(default=None, ge=0, le=1_000_000)

    # Feature toggles (keep defaults conservative).
    enable_pdf_quality: bool = True
    enable_text_extract: bool = True
    enable_pii: bool = False
    enable_secrets: bool = False
    compute_file_hash: bool = False

    # Optional overrides for extraction limits.
    pdf_sample_pages: int | None = Field(default=None, ge=1, le=50)
    text_extract_max_bytes: int | None = Field(default=None, ge=1_000, le=50_000_000)

    # Optional PDF page-type heuristics (used for scan_ratio/low_density_ratio metrics; best-effort).
    pdf_min_text_chars_per_page: int | None = Field(default=None, ge=0, le=20_000)
    pdf_text_chars_per_page: int | None = Field(default=None, ge=0, le=50_000)
    pdf_scan_ratio_threshold: float | None = Field(default=None, ge=0.0, le=1.0)

    # Privacy: when enabled, API responses will not include real paths (only aliases).
    redact_paths: bool = False

    # Optional: include masked match samples (for internal review; off by default).
    enable_pii_samples: bool = False
    pii_context_chars: int | None = Field(default=None, ge=0, le=500)
    pii_max_samples_per_file: int | None = Field(default=None, ge=0, le=50)

    enable_secrets_samples: bool = False
    secrets_context_chars: int | None = Field(default=None, ge=0, le=500)
    secrets_max_samples_per_file: int | None = Field(default=None, ge=0, le=50)

    # Optional: near-duplicate candidate detection (SimHash on extracted text samples).
    enable_near_dup: bool = False
    near_dup_hamming_threshold: int | None = Field(default=None, ge=0, le=32)
    near_dup_max_pairs: int | None = Field(default=None, ge=0, le=100_000)

    # Optional: representative sampling (for pricing/POC). Writes a sample list into run artifacts.
    enable_sampling: bool = True
    sample_size: int | None = Field(default=None, ge=0, le=2000)
    threshold_overrides: dict[str, Any] | None = None

    # Optional: incremental scan reuse (reuse unchanged file records from a previous run).
    reuse_unchanged_files: bool = False
    reuse_from_scan_run_id: UUID | None = None


class DatasetPrecheckScanRunOut(BaseModel):
    id: UUID
    tenant_id: UUID
    dataset_id: UUID
    requested_by: str | None = None
    kind: str
    status: str
    progress: int
    config: dict[str, Any] = Field(default_factory=dict)
    summary: dict[str, Any] = Field(default_factory=dict)
    artifacts: dict[str, Any] = Field(default_factory=dict)
    error_message: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class DatasetPrecheckScanRunListResponse(BaseModel):
    total: int
    items: list[DatasetPrecheckScanRunOut] = Field(default_factory=list)


# ==================== Extras (samples / near-dup / diff / suggestions) ====================


class DatasetPrecheckSamplesResponse(BaseModel):
    """
    Representative samples payload for pricing/POC alignment.

    Note: Items reuse DatasetPrecheckFileOut (already redacted/aliased when redact_paths=true).
    """

    requested: int = 0
    strata_count: int = 0
    representative: list[DatasetPrecheckFileOut] = Field(default_factory=list)
    needs_review: dict[str, list[DatasetPrecheckFileOut]] = Field(default_factory=dict)
    top_large_files: list[DatasetPrecheckFileOut] = Field(default_factory=list)
    top_long_text: list[DatasetPrecheckFileOut] = Field(default_factory=list)


class DatasetPrecheckSampleReviewPatchRequest(BaseModel):
    file_name: str = Field(min_length=1, max_length=4096)
    disposition: Literal["approved", "manual"]


class DatasetPrecheckSampleReviewOut(BaseModel):
    file_name: str
    review_disposition: Literal["approved", "manual"]
    reviewed_at: datetime
    reviewed_by: str | None = None


class DatasetPrecheckNearDupCluster(BaseModel):
    id: str
    members: list[str] = Field(default_factory=list)


class DatasetPrecheckNearDupPair(BaseModel):
    a: str
    b: str
    distance: int


class DatasetPrecheckNearDupResponse(BaseModel):
    threshold: int = 0
    max_pairs: int = 0
    pairs_returned: int = 0
    clusters_returned: int = 0
    clusters: list[DatasetPrecheckNearDupCluster] = Field(default_factory=list)
    pairs: list[DatasetPrecheckNearDupPair] = Field(default_factory=list)


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

    by_file_type: list[DatasetPrecheckDiffItem] = Field(default_factory=list)
    findings: list[DatasetPrecheckDiffItem] = Field(default_factory=list)


class DatasetPrecheckManualReviewBucket(BaseModel):
    """
    A bounded list of file names that likely require manual review.
    """

    key: str
    total: int = 0
    sample_names: list[str] = Field(default_factory=list)


class DatasetPrecheckIngestionSuggestionResponse(BaseModel):
    """
    Suggested, importable ingestion policy + manual-review buckets derived from a precheck run.
    """

    generated_at: datetime
    before_policy: IngestionPolicy | None = None
    policy: IngestionPolicy
    policy_diff: dict[str, Any] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)
    manual_review: list[DatasetPrecheckManualReviewBucket] = Field(default_factory=list)

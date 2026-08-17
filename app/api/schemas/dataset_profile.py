"""
Dataset profile / scan schemas.

These schemas are used to:
- Return real-time dataset profiling summary (fast, computed on demand)
- Track deep scan runs (async backfill + persisted summary)
"""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class DatasetProfileHistogramBin(BaseModel):
    label: str
    min: int | None = None
    max: int | None = None
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


class DatasetProfileParsingProvenanceStats(BaseModel):
    """
    Best-effort parse routing/provenance aggregation.

    Populated from per-document metadata.parse_provenance (when available).
    """

    docs_with_provenance: int = 0
    by_resolved_backend: dict[str, int] = Field(default_factory=dict)
    fallback_docs: int = 0
    elapsed_ms_percentiles: DatasetProfilePercentiles = Field(default_factory=DatasetProfilePercentiles)


class DatasetProfileTargetCheck(BaseModel):
    """
    Best-effort target checks for tuning (objective signals + suggestions).

    Designed to be stable for UI/report rendering:
    - status is one of pass/warn/fail
    - observed/target are JSON-safe dicts for drill-down
    """

    key: str
    label: str
    status: Literal["pass", "warn", "fail"] = "pass"
    observed: dict[str, Any] = Field(default_factory=dict)
    target: dict[str, Any] = Field(default_factory=dict)
    message: str | None = None
    suggestions: list[str] = Field(default_factory=list)


class DatasetProfileFindingSummary(BaseModel):
    key: str
    label: str
    severity: Literal["info", "warning", "error"] = "info"
    count: int = 0
    description: str | None = None


class DatasetProfileRecallRiskHint(BaseModel):
    """
    Best-effort recall-risk hints derived from lightweight profile signals.

    Hints are advisory and must not block ingest/indexing.
    """

    key: str
    label: str
    severity: Literal["info", "warning", "error"] = "warning"
    observed: dict[str, Any] = Field(default_factory=dict)
    target: dict[str, Any] = Field(default_factory=dict)
    message: str | None = None
    suggestions: list[str] = Field(default_factory=list)


class DatasetProfileScanRunSummary(BaseModel):
    id: UUID
    kind: str = "deep"
    status: str = "pending"
    progress: int = 0
    requested_by: str | None = None
    created_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error_message: str | None = None


class DatasetProfileSummary(BaseModel):
    dataset_id: UUID
    generated_at: datetime

    total_documents: int = 0
    total_size_bytes: int = 0
    by_status: dict[str, int] = Field(default_factory=dict)
    by_file_type: dict[str, int] = Field(default_factory=dict)
    # Stable "slice" distributions (align with eval slicing).
    by_directory: dict[str, int] = Field(default_factory=dict)
    by_quality_bucket: dict[str, int] = Field(default_factory=dict)

    file_size_histogram: list[DatasetProfileHistogramBin] = Field(default_factory=list)

    # Text length based on `total_characters` (best-effort).
    length_percentiles: DatasetProfilePercentiles = Field(default_factory=DatasetProfilePercentiles)
    length_histogram: list[DatasetProfileHistogramBin] = Field(default_factory=list)

    # Chunking proxies derived from persisted per-document stats (cheap, best-effort).
    # Note: these are document-level distributions, NOT per-chunk distributions.
    chunk_count_percentiles: DatasetProfilePercentiles = Field(default_factory=DatasetProfilePercentiles)
    chunk_count_histogram: list[DatasetProfileHistogramBin] = Field(default_factory=list)
    avg_chunk_chars_percentiles: DatasetProfilePercentiles = Field(default_factory=DatasetProfilePercentiles)
    avg_chunk_chars_histogram: list[DatasetProfileHistogramBin] = Field(default_factory=list)

    # Chunk length distribution (per-chunk; best-effort).
    # This is derived from persisted per-document `chunking_stats.histogram` (ingest-time or deep-scan backfill).
    chunk_length_percentiles: DatasetProfilePercentiles = Field(default_factory=DatasetProfilePercentiles)
    chunk_length_histogram: list[DatasetProfileHistogramBin] = Field(default_factory=list)

    # Token-based chunk stats (best-effort; derived from per-document `chunking_stats_tokens`).
    chunk_token_percentiles: DatasetProfilePercentiles = Field(default_factory=DatasetProfilePercentiles)
    chunk_token_histogram: list[DatasetProfileHistogramBin] = Field(default_factory=list)
    avg_chunk_tokens_percentiles: DatasetProfilePercentiles = Field(default_factory=DatasetProfilePercentiles)
    avg_chunk_tokens_histogram: list[DatasetProfileHistogramBin] = Field(default_factory=list)

    # Chunk coverage / overlap waste (best-effort; derived from per-document `chunk_coverage`).
    # Note: Percentiles/histograms are expressed in percentage points (0-100).
    chunk_coverage_percentiles: DatasetProfilePercentiles = Field(default_factory=DatasetProfilePercentiles)
    chunk_coverage_histogram: list[DatasetProfileHistogramBin] = Field(default_factory=list)
    chunk_overlap_waste_percentiles: DatasetProfilePercentiles = Field(default_factory=DatasetProfilePercentiles)
    chunk_overlap_waste_histogram: list[DatasetProfileHistogramBin] = Field(default_factory=list)

    # Additional distributions (best-effort; may be empty if metadata missing).
    page_number_histogram: list[DatasetProfileHistogramBin] = Field(default_factory=list)
    parse_quality_histogram: list[DatasetProfileHistogramBin] = Field(default_factory=list)
    language_mix: dict[str, int] = Field(default_factory=dict)

    pdf_scan: DatasetProfilePdfScanStats = Field(default_factory=DatasetProfilePdfScanStats)
    parsing_provenance: DatasetProfileParsingProvenanceStats = Field(
        default_factory=DatasetProfileParsingProvenanceStats
    )

    pii_hits_total: dict[str, int] = Field(default_factory=dict)
    secrets_hits_total: dict[str, int] = Field(default_factory=dict)

    # Actionable buckets.
    findings: list[DatasetProfileFindingSummary] = Field(default_factory=list)

    # Retrieval recall-risk hints (best-effort; non-blocking).
    recall_risk_hints: list[DatasetProfileRecallRiskHint] = Field(default_factory=list)

    # Target checks for chunk tuning (best-effort; may be empty when stats missing).
    chunk_targets: list[DatasetProfileTargetCheck] = Field(default_factory=list)

    # Best-effort last deep scan run metadata (may be None).
    latest_scan_run: DatasetProfileScanRunSummary | None = None


class DatasetProfileDocumentOut(BaseModel):
    id: UUID
    dataset_id: UUID | None = None
    filename: str
    file_type: str
    file_size: int
    status: str
    chunk_count: int = 0
    total_characters: int = 0
    created_at: datetime | None = None
    updated_at: datetime | None = None
    error_message: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    # Optional PII-safe preview snippet (used by bucket drilldowns / reports).
    preview: str | None = None
    preview_truncated: bool = False


class DatasetProfileFindingListResponse(BaseModel):
    total: int
    items: list[DatasetProfileDocumentOut] = Field(default_factory=list)


class DatasetProfileDocumentListResponse(BaseModel):
    """
    Generic document list response used by profile drilldowns (not just findings).
    """

    total: int
    items: list[DatasetProfileDocumentOut] = Field(default_factory=list)


class DatasetProfileScanRunCreateRequest(BaseModel):
    backfill_pdf_quality: bool = True
    backfill_text_quality: bool = True
    backfill_chunk_stats: bool = True
    # Chunk extras are OFF by default (can be expensive; enable explicitly).
    backfill_chunk_token_stats: bool = False
    backfill_chunk_coverage: bool = False
    backfill_chunk_quality_gate: bool = False
    compute_file_hash: bool = False
    # Hard cap for safety; 0/None means no cap.
    max_documents: int | None = Field(default=None, ge=0, le=1_000_000)


class DatasetProfileScanRunOut(BaseModel):
    id: UUID
    tenant_id: UUID
    dataset_id: UUID
    requested_by: str | None = None
    kind: str
    status: str
    progress: int
    config: dict[str, Any] = Field(default_factory=dict)
    summary: dict[str, Any] = Field(default_factory=dict)
    error_message: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class DatasetProfileScanRunListResponse(BaseModel):
    total: int
    items: list[DatasetProfileScanRunOut] = Field(default_factory=list)

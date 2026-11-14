"""
EvidenceSuite / EvidenceItem API schemas.

These schemas power the Evidence Workbench (enterprise ground-truth evidence management):
- Draft/review/approve lifecycle
- Retrieval snapshot storage (best-effort) for reproducibility
- Sync into RAGAS regression cases for retrieval-only evaluation
"""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.api.schemas.base import OrmModel
from app.api.schemas.evaluation.regression import ReferenceSource

EvidenceItemStatus = Literal["draft", "reviewed", "approved", "archived"]


class EvidenceReferenceRepairQuery(BaseModel):
    async_mode: bool = Field(default=False, description="Enqueue repair via task queue (arq)")


class EvidenceSuiteListQuery(BaseModel):
    skip: int = Field(default=0, ge=0)
    limit: int = Field(default=50, ge=1, le=200)
    dataset_id: UUID | None = None
    include_archived: bool = False


class EvidenceSuiteDashboardQuery(BaseModel):
    include_archived_items: bool = False
    top_n: int = Field(default=12, ge=1, le=50)
    heatmap_top_n: int = Field(default=8, ge=2, le=20)


class EvidenceHardcaseDiscoveryQuery(BaseModel):
    window_minutes: int = Field(default=7 * 24 * 60, ge=1, le=60 * 24 * 30)
    max_bytes: int = Field(default=10_000_000, ge=100000, le=50000000)
    max_feedback_rows: int = Field(default=500, ge=1, le=5000)
    max_candidates: int = Field(default=50, ge=0, le=200)
    max_rating: int = Field(default=2, ge=1, le=5)
    include_existing: bool = False


class EvidenceReferenceDriftAuditQuery(BaseModel):
    include_archived_items: bool = False
    include_details: bool = True
    details_limit: int = Field(default=200, ge=0, le=2000)
    slice_top_n: int = Field(default=20, ge=1, le=200)


class EvidenceItemImportQuery(BaseModel):
    max_items: int = Field(default=2000, ge=1, le=10000)


class EvidenceItemListQuery(BaseModel):
    skip: int = Field(default=0, ge=0)
    limit: int = Field(default=50, ge=1, le=200)
    status: str | None = None


class EvidenceSuiteExportQuery(BaseModel):
    include_archived_items: bool = False


class EvidenceTrainingExportQuery(BaseModel):
    dataset_id: UUID = Field(description="Dataset id to export")
    format: str = Field(default="jsonl", description="jsonl or csv")
    include_feedback: bool = True
    include_evidence: bool = True
    include_archived_evidence: bool = False
    max_rows_per_source: int = Field(default=2000, ge=1, le=10000)


class EvidenceSuiteCreateRequest(BaseModel):
    dataset_id: UUID
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    tags: list[str] = Field(default_factory=list)
    config: dict[str, Any] = Field(default_factory=dict)


class EvidenceSuitePatchRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    tags: list[str] | None = None
    config: dict[str, Any] | None = None
    archived_at: datetime | None = None

    @model_validator(mode="after")
    def _non_empty_patch(self) -> "EvidenceSuitePatchRequest":
        if not self.model_fields_set:
            raise ValueError("No fields to patch")
        return self


class EvidenceSuiteOut(OrmModel):
    id: UUID
    tenant_id: UUID
    dataset_id: UUID
    name: str
    description: str | None = None
    tags: list[str] = Field(default_factory=list)
    config: dict[str, Any] = Field(default_factory=dict)
    created_by: str | None = None
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None = None

    # Aggregated counts (best-effort; may be omitted in some endpoints).
    item_counts: dict[str, int] | None = None


class EvidenceSuiteList(BaseModel):
    total: int
    items: list[EvidenceSuiteOut] = Field(default_factory=list)


class EvidenceItemCreateRequest(BaseModel):
    suite_id: UUID
    dataset_id: UUID
    query: str = Field(min_length=1)
    expected_answer: str | None = None
    tags: list[str] = Field(default_factory=list)
    source_metadata: dict[str, Any] = Field(default_factory=dict)
    reference_sources: list[ReferenceSource] = Field(min_length=1)

    # Best-effort snapshots for reproducibility/audit.
    retrieval_snapshot: dict[str, Any] = Field(default_factory=dict)
    rag_config_snapshot: dict[str, Any] = Field(default_factory=dict)
    notes: str | None = None


class EvidenceItemPatchRequest(BaseModel):
    query: str | None = Field(default=None, min_length=1)
    expected_answer: str | None = None
    tags: list[str] | None = None
    source_metadata: dict[str, Any] | None = None
    reference_sources: list[ReferenceSource] | None = Field(default=None, min_length=1)
    retrieval_snapshot: dict[str, Any] | None = None
    rag_config_snapshot: dict[str, Any] | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def _non_empty_patch(self) -> "EvidenceItemPatchRequest":
        if not self.model_fields_set:
            raise ValueError("No fields to patch")
        return self


class EvidenceItemOut(OrmModel):
    id: UUID
    tenant_id: UUID
    dataset_id: UUID
    suite_id: UUID
    status: EvidenceItemStatus

    query: str
    expected_answer: str | None = None
    tags: list[str] = Field(default_factory=list)
    source_metadata: dict[str, Any] = Field(default_factory=dict)
    reference_sources: list[ReferenceSource] = Field(default_factory=list)
    retrieval_snapshot: dict[str, Any] = Field(default_factory=dict)
    rag_config_snapshot: dict[str, Any] = Field(default_factory=dict)
    notes: str | None = None

    regression_case_id: UUID | None = None

    created_by: str | None = None
    reviewed_by: str | None = None
    approved_by: str | None = None
    archived_by: str | None = None

    reviewed_at: datetime | None = None
    approved_at: datetime | None = None
    archived_at: datetime | None = None

    created_at: datetime
    updated_at: datetime


class EvidenceItemList(BaseModel):
    total: int
    items: list[EvidenceItemOut] = Field(default_factory=list)


class EvidenceSuiteSyncRegressionResponse(BaseModel):
    suite_id: UUID
    dataset_id: UUID
    created: int = 0
    updated: int = 0
    skipped: int = 0
    errors: list[dict[str, Any]] = Field(default_factory=list)


class EvidenceSuiteExportSuite(BaseModel):
    id: str
    name: str
    description: str | None
    tags: list[str]
    config: dict[str, Any]
    created_by: str | None
    created_at: str | None
    updated_at: str | None


class EvidenceSuiteExportItem(BaseModel):
    id: str
    status: str
    query: str
    expected_answer: str | None
    tags: list[str]
    source_metadata: dict[str, Any]
    reference_sources: list[dict[str, Any]]
    retrieval_snapshot: dict[str, Any]
    rag_config_snapshot: dict[str, Any]
    notes: str | None
    regression_case_id: str | None
    created_by: str | None
    reviewed_by: str | None
    approved_by: str | None
    archived_by: str | None
    reviewed_at: str | None
    approved_at: str | None
    archived_at: str | None
    created_at: str | None
    updated_at: str | None


class EvidenceSuiteExportV1(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    schema_: str = Field(default="mimirq.evidence_suite.v1", alias="schema", serialization_alias="schema")
    exported_at: str
    dataset_id: UUID
    suite: EvidenceSuiteExportSuite
    items: list[EvidenceSuiteExportItem]

    @property
    def schema(self) -> str:
        return self.schema_


class EvidenceTrainingExportRow(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    schema_: str = Field(default="mimirq.training_export_row.v1", alias="schema", serialization_alias="schema")
    source_type: Literal["feedback", "evidence_item"]
    source_id: str
    dataset_id: UUID | None
    status: str
    question: str
    expected_answer: str | None
    tags: list[str]
    reference_sources: list[dict[str, Any]]
    trace_snapshot: dict[str, Any]
    rag_config_snapshot: dict[str, Any]
    source_metadata: dict[str, Any]
    created_at: str | None
    updated_at: str | None


class EvidenceItemImportResponse(BaseModel):
    suite_id: UUID
    dataset_id: UUID
    parsed: int = 0
    created: int = 0
    skipped: int = 0
    errors: list[dict[str, Any]] = Field(default_factory=list)


class EvidenceCoverageBucket(BaseModel):
    key: str
    items: int = 0
    references: int = 0


class EvidenceCoverageHeatmap(BaseModel):
    x: list[str] = Field(default_factory=list)
    y: list[str] = Field(default_factory=list)
    z: list[list[int]] = Field(default_factory=list)
    metric: str = "items"


class EvidenceSuiteCoverage(BaseModel):
    language: list[EvidenceCoverageBucket] = Field(default_factory=list)
    file_type: list[EvidenceCoverageBucket] = Field(default_factory=list)
    quality_bucket: list[EvidenceCoverageBucket] = Field(default_factory=list)
    channel: list[EvidenceCoverageBucket] = Field(default_factory=list)
    heatmaps: dict[str, EvidenceCoverageHeatmap] = Field(default_factory=dict)


class EvidenceThroughputWindow(BaseModel):
    created: int = 0
    reviewed: int = 0
    approved: int = 0


class EvidenceLeadTimeStats(BaseModel):
    count: int = 0
    p50_sec: float | None = None
    p90_sec: float | None = None
    mean_sec: float | None = None


class EvidenceSuiteThroughput(BaseModel):
    window_days: int = 7
    last_window: EvidenceThroughputWindow = Field(default_factory=EvidenceThroughputWindow)
    draft_to_reviewed: EvidenceLeadTimeStats = Field(default_factory=EvidenceLeadTimeStats)
    reviewed_to_approved: EvidenceLeadTimeStats = Field(default_factory=EvidenceLeadTimeStats)
    draft_to_approved: EvidenceLeadTimeStats = Field(default_factory=EvidenceLeadTimeStats)


class EvidenceSuiteDashboardOut(BaseModel):
    generated_at: datetime
    suite_id: UUID
    dataset_id: UUID
    item_counts: dict[str, int] = Field(default_factory=dict)
    coverage: EvidenceSuiteCoverage = Field(default_factory=EvidenceSuiteCoverage)
    throughput: EvidenceSuiteThroughput = Field(default_factory=EvidenceSuiteThroughput)


class EvidenceHardcaseCandidateOut(BaseModel):
    """
    PII-safe hardcase candidate (clustered by question_hash).

    Notes:
    - `question_hash` matches metrics JSONL `question_hash` (sha256[:16] of stripped question text)
    - IDs (feedback_id/request_id) are pointers for reviewers; no raw text is included.
    """

    question_hash: str
    cluster_size: int = 0
    in_suite: bool = False

    feedback_ids: list[str] = Field(default_factory=list)
    request_ids: list[str] = Field(default_factory=list)

    retrieval_config_hash: str | None = None
    citations_count: int | None = None
    retrieval_error_kinds: dict[str, int] = Field(default_factory=dict)
    rag_config_template: dict[str, Any] | None = None


class EvidenceHardcaseDiscoveryOut(BaseModel):
    generated_at: datetime
    suite_id: UUID
    dataset_id: UUID

    enabled: bool = True
    metrics_path: str
    window_minutes: int
    max_bytes: int
    truncated: bool = False

    feedback_scanned: int = 0
    trace_index_size: int = 0
    candidates: list[EvidenceHardcaseCandidateOut] = Field(default_factory=list)

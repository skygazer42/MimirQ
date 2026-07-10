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
from app.api.schemas.regression import ReferenceSource

EvidenceItemStatus = Literal["draft", "reviewed", "approved", "archived"]


class EvidenceSuiteCreateRequest(BaseModel):
    dataset_id: UUID
    name: str = Field(..., min_length=1, max_length=255)
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
    def _non_empty_patch(self):
        if not (getattr(self, "model_fields_set", None) or set()):
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
    query: str = Field(..., min_length=1)
    expected_answer: str | None = None
    tags: list[str] = Field(default_factory=list)
    source_metadata: dict[str, Any] = Field(default_factory=dict)
    reference_sources: list[ReferenceSource] = Field(..., min_length=1)

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
    def _non_empty_patch(self):
        if not (getattr(self, "model_fields_set", None) or set()):
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


class EvidenceSuiteExportV1(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    schema_: str = Field(default="mimirq.evidence_suite.v1", alias="schema", serialization_alias="schema")
    exported_at: str
    dataset_id: UUID
    suite: dict[str, Any]
    items: list[dict[str, Any]]

    @property
    def schema(self) -> str:
        return str(self.schema_)


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

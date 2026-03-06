"""
EvidenceSuite / EvidenceItem API schemas.

These schemas power the Evidence Workbench (enterprise ground-truth evidence management):
- Draft/review/approve lifecycle
- Retrieval snapshot storage (best-effort) for reproducibility
- Sync into RAGAS regression cases for retrieval-only evaluation
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from app.api.schemas.base import OrmModel
from app.api.schemas.regression import ReferenceSource

EvidenceItemStatus = Literal["draft", "reviewed", "approved", "archived"]


class EvidenceSuiteCreateRequest(BaseModel):
    dataset_id: UUID
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    config: Dict[str, Any] = Field(default_factory=dict)


class EvidenceSuitePatchRequest(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    description: Optional[str] = None
    tags: Optional[List[str]] = None
    config: Optional[Dict[str, Any]] = None
    archived_at: Optional[datetime] = None

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
    description: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    config: Dict[str, Any] = Field(default_factory=dict)
    created_by: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    archived_at: Optional[datetime] = None

    # Aggregated counts (best-effort; may be omitted in some endpoints).
    item_counts: Optional[Dict[str, int]] = None


class EvidenceSuiteList(BaseModel):
    total: int
    items: List[EvidenceSuiteOut] = Field(default_factory=list)


class EvidenceItemCreateRequest(BaseModel):
    suite_id: UUID
    dataset_id: UUID
    query: str = Field(..., min_length=1)
    expected_answer: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    source_metadata: Dict[str, Any] = Field(default_factory=dict)
    reference_sources: List[ReferenceSource] = Field(..., min_length=1)

    # Best-effort snapshots for reproducibility/audit.
    retrieval_snapshot: Dict[str, Any] = Field(default_factory=dict)
    rag_config_snapshot: Dict[str, Any] = Field(default_factory=dict)
    notes: Optional[str] = None


class EvidenceItemPatchRequest(BaseModel):
    query: Optional[str] = Field(default=None, min_length=1)
    expected_answer: Optional[str] = None
    tags: Optional[List[str]] = None
    source_metadata: Optional[Dict[str, Any]] = None
    reference_sources: Optional[List[ReferenceSource]] = Field(default=None, min_length=1)
    retrieval_snapshot: Optional[Dict[str, Any]] = None
    rag_config_snapshot: Optional[Dict[str, Any]] = None
    notes: Optional[str] = None

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
    expected_answer: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    source_metadata: Dict[str, Any] = Field(default_factory=dict)
    reference_sources: List[ReferenceSource] = Field(default_factory=list)
    retrieval_snapshot: Dict[str, Any] = Field(default_factory=dict)
    rag_config_snapshot: Dict[str, Any] = Field(default_factory=dict)
    notes: Optional[str] = None

    regression_case_id: Optional[UUID] = None

    created_by: Optional[str] = None
    reviewed_by: Optional[str] = None
    approved_by: Optional[str] = None
    archived_by: Optional[str] = None

    reviewed_at: Optional[datetime] = None
    approved_at: Optional[datetime] = None
    archived_at: Optional[datetime] = None

    created_at: datetime
    updated_at: datetime


class EvidenceItemList(BaseModel):
    total: int
    items: List[EvidenceItemOut] = Field(default_factory=list)


class EvidenceSuiteSyncRegressionResponse(BaseModel):
    suite_id: UUID
    dataset_id: UUID
    created: int = 0
    updated: int = 0
    skipped: int = 0
    errors: List[Dict[str, Any]] = Field(default_factory=list)


class EvidenceSuiteExportV1(BaseModel):
    schema: str = "mimirq.evidence_suite.v1"
    exported_at: str
    dataset_id: UUID
    suite: Dict[str, Any]
    items: List[Dict[str, Any]]


class EvidenceItemImportResponse(BaseModel):
    suite_id: UUID
    dataset_id: UUID
    parsed: int = 0
    created: int = 0
    skipped: int = 0
    errors: List[Dict[str, Any]] = Field(default_factory=list)


class EvidenceCoverageBucket(BaseModel):
    key: str
    items: int = 0
    references: int = 0


class EvidenceCoverageHeatmap(BaseModel):
    x: List[str] = Field(default_factory=list)
    y: List[str] = Field(default_factory=list)
    z: List[List[int]] = Field(default_factory=list)
    metric: str = "items"


class EvidenceSuiteCoverage(BaseModel):
    language: List[EvidenceCoverageBucket] = Field(default_factory=list)
    file_type: List[EvidenceCoverageBucket] = Field(default_factory=list)
    quality_bucket: List[EvidenceCoverageBucket] = Field(default_factory=list)
    channel: List[EvidenceCoverageBucket] = Field(default_factory=list)
    heatmaps: Dict[str, EvidenceCoverageHeatmap] = Field(default_factory=dict)


class EvidenceThroughputWindow(BaseModel):
    created: int = 0
    reviewed: int = 0
    approved: int = 0


class EvidenceLeadTimeStats(BaseModel):
    count: int = 0
    p50_sec: Optional[float] = None
    p90_sec: Optional[float] = None
    mean_sec: Optional[float] = None


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
    item_counts: Dict[str, int] = Field(default_factory=dict)
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

    feedback_ids: List[str] = Field(default_factory=list)
    request_ids: List[str] = Field(default_factory=list)

    retrieval_config_hash: Optional[str] = None
    citations_count: Optional[int] = None
    retrieval_error_kinds: Dict[str, int] = Field(default_factory=dict)
    rag_config_template: Optional[Dict[str, Any]] = None


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
    candidates: List[EvidenceHardcaseCandidateOut] = Field(default_factory=list)

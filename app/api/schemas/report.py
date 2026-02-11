"""Report-related Pydantic schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field

from app.api.schemas.dataset_profile import DatasetProfileSummary
from app.api.schemas.document_folders import DocumentFolderTreeResponse


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


class DatasetGovernanceMetricsOut(BaseModel):
    """Best-effort governance metrics aggregated from per-document metadata."""

    total_documents: int = 0
    used_documents: int = 0
    truncated: bool = False

    docs_with_governance: int = 0
    rules_applied_total: int = 0
    changed_documents_total: int = 0
    dropped_documents_total: int = 0

    drop_reasons_total: Dict[str, int] = Field(default_factory=dict)
    rule_packs_docs: Dict[str, int] = Field(default_factory=dict)


class DatasetChunkQualityMetricsOut(BaseModel):
    """Best-effort chunking quality metrics aggregated from per-document metadata."""

    total_documents: int = 0
    used_documents: int = 0
    truncated: bool = False

    gate_grade_docs: Dict[str, int] = Field(default_factory=dict)
    coverage_low_documents: int = 0
    overlap_waste_high_documents: int = 0
    token_stats_missing_documents: int = 0


class DatasetKGEntityTypeCount(BaseModel):
    type: str
    count: int = 0


class DatasetKGTopDocumentOut(BaseModel):
    """Best-effort KG drilldown row scoped by document-level ACL."""

    document_id: UUID
    source: Optional[str] = None
    event_count: int = 0
    skipped_chunks: int = 0
    skipped_short_chunks: int = 0
    failed_chunks: int = 0
    retry_chunks: int = 0


class DatasetKGStatsOut(BaseModel):
    """Best-effort Knowledge Graph (KG) metrics scoped by document-level ACL."""

    events: int = 0
    entities: int = 0
    links: int = 0
    # Traceability / completeness (best-effort).
    events_with_document_id: int = 0
    events_with_chunk_id: int = 0
    events_with_page_ref: int = 0
    links_with_provenance: int = 0
    links_with_page_ref: int = 0

    # Incremental / extraction audit (best-effort; derived from document metadata).
    documents_with_kg_extracted_at: int = 0
    documents_with_kg_events: int = 0
    event_count_from_documents: int = 0
    skipped_chunks_total: int = 0
    skipped_short_chunks_total: int = 0
    failed_chunks_total: int = 0
    retry_chunks_total: int = 0

    # Optional drilldowns (bounded).
    top_documents: List[DatasetKGTopDocumentOut] = Field(default_factory=list)
    entity_types: List[DatasetKGEntityTypeCount] = Field(default_factory=list)
    updated_at: Optional[datetime] = None


class DatasetRegressionRunSummaryOut(BaseModel):
    """Best-effort latest regression run snapshot for the dataset (objective numbers only)."""

    run_id: UUID
    status: str
    metrics: List[str] = Field(default_factory=list)
    params: Dict[str, Any] = Field(default_factory=dict)
    summary: Dict[str, Any] = Field(default_factory=dict)
    error_message: Optional[str] = None
    created_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None


class DatasetReportOut(BaseModel):
    dataset_id: UUID
    dataset_name: Optional[str] = None
    pipeline_hash: Optional[str] = None
    generated_at: datetime

    profile: DatasetProfileSummary
    compliance: ComplianceSummary
    pipeline_versions: List[PipelineVersionSummary] = Field(default_factory=list)
    # Best-effort per-pipeline version provenance snapshots (keyed by pipeline_hash).
    pipeline_snapshots: Dict[str, Any] = Field(default_factory=dict)
    connectors: List[ConnectorRunSummary] = Field(default_factory=list)

    # A snapshot of dataset-level config (best-effort), useful for sharing.
    dataset_metadata: Dict[str, Any] = Field(default_factory=dict)

    # Optional: dataset folder tree derived from document.metadata.source_path (best-effort).
    folder_tree: Optional[DocumentFolderTreeResponse] = None

    # Optional: governance metrics derived from document.metadata.governance_* (best-effort).
    governance_metrics: Optional[DatasetGovernanceMetricsOut] = None

    # Optional: chunking quality metrics derived from document.metadata.chunk_* (best-effort).
    chunk_quality_metrics: Optional[DatasetChunkQualityMetricsOut] = None

    # Optional: KG stats for the dataset, filtered by doc-level ACL (best-effort).
    kg_stats: Optional[DatasetKGStatsOut] = None

    # Optional: latest regression run summary for the dataset (best-effort).
    latest_regression_run: Optional[DatasetRegressionRunSummaryOut] = None

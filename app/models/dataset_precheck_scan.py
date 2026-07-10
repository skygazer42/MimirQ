"""
Dataset precheck scan run database model.

Precheck scans are intended for "before ingestion" analysis:
- scan a local folder (mounted to the backend container/host)
- compute objective stats (format distribution, size/length, scanned PDFs, PII/secrets hits, duplicates, etc.)
- persist run progress + a summary snapshot for audit/sharing

Heavy per-file details are stored on disk as JSONL under uploads/{tenant}/precheck/{run_id}/files.jsonl
and queried on demand (drill-down).
"""


import uuid

from sqlalchemy import Column, DateTime, ForeignKeyConstraint, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.sql import func

from app.core.database import Base


class DatasetPrecheckScanRun(Base):
    __tablename__ = "dataset_precheck_scan_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    dataset_id = Column(UUID(as_uuid=True), nullable=False, index=True)

    requested_by = Column(String(255), nullable=True)

    # Run kind:
    # - path: scan a local folder path (mounted/available to the API process)
    kind = Column(String(32), nullable=False, default="path")

    # Status lifecycle: pending -> running -> completed | failed | cancelled
    status = Column(String(32), nullable=False, default="pending")
    progress = Column(Integer, nullable=False, default=0)  # 0-100

    # User-provided options / thresholds (stored for reproducibility).
    config = Column(JSONB, nullable=False, default=dict)

    # Persisted summary payload (mirrors DatasetPrecheckSummary schema).
    summary = Column(JSONB, nullable=False, default=dict)

    # Pointer to on-disk artifacts (JSONL/HTML), stored as small strings for portability.
    artifacts = Column(JSONB, nullable=False, default=dict)

    error_message = Column(Text, nullable=True)

    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "dataset_id"],
            ["datasets.tenant_id", "datasets.id"],
            name="fk_dataset_precheck_scan_runs_tenant_dataset",
            ondelete="CASCADE",
        ),
        Index("ix_dataset_precheck_scan_runs_tenant_dataset_created_at", "tenant_id", "dataset_id", "created_at"),
        Index("ix_dataset_precheck_scan_runs_tenant_status_created_at", "tenant_id", "status", "created_at"),
    )

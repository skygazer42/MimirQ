"""
Dataset-level profiling / scan run database model.

This table stores *runs* of potentially expensive dataset scans (backfill, deep checks).
The real-time "profile summary" endpoint can compute on demand, while deep scans
persist their computed summary for audit and progress tracking.
"""


import uuid

from sqlalchemy import Column, DateTime, ForeignKeyConstraint, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.sql import func

from app.core.database import Base


class DatasetProfileScanRun(Base):
    __tablename__ = "dataset_profile_scan_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    dataset_id = Column(UUID(as_uuid=True), nullable=False, index=True)

    # Who initiated the scan (for audit).
    requested_by = Column(String(255), nullable=True)

    # Run kind:
    # - deep: backfill missing per-document metrics and compute a persisted summary
    kind = Column(String(32), nullable=False, default="deep")

    # Status lifecycle: pending -> running -> completed | failed | cancelled
    status = Column(String(32), nullable=False, default="pending")
    progress = Column(Integer, nullable=False, default=0)  # 0-100

    # User-provided options / thresholds (stored for reproducibility).
    config = Column(JSONB, nullable=False, default=dict)

    # Persisted summary payload (mirrors DatasetProfileSummary schema).
    summary = Column(JSONB, nullable=False, default=dict)

    error_message = Column(Text, nullable=True)

    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "dataset_id"],
            ["datasets.tenant_id", "datasets.id"],
            name="fk_dataset_profile_scan_runs_tenant_dataset",
            ondelete="CASCADE",
        ),
        Index("ix_dataset_profile_scan_runs_tenant_dataset_created_at", "tenant_id", "dataset_id", "created_at"),
        Index("ix_dataset_profile_scan_runs_tenant_status_created_at", "tenant_id", "status", "created_at"),
    )

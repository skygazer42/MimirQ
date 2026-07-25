"""
Ingestion run manifest models.

Goal:
- Provide a unified "run_id" view for all ingestion entrypoints (upload/batch/URL/connector).
- Track run-level status/stats/errors and map runs -> documents.

This is intentionally lightweight and "best-effort" (enterprise observability).
"""


import uuid

from sqlalchemy import Column, DateTime, ForeignKey, ForeignKeyConstraint, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.core.database import Base


class IngestionRun(Base):
    """Unified ingestion run manifest."""

    __tablename__ = "ingestion_runs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "dataset_id"],
            ["datasets.tenant_id", "datasets.id"],
            name="fk_ingestion_runs_tenant_dataset",
            ondelete="CASCADE",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    dataset_id = Column(UUID(as_uuid=True), nullable=True, index=True)

    # Kind examples:
    # - upload / upload_batch / upload_url
    # - connector:url_batch / connector:web_crawl / ...
    kind = Column(String(80), nullable=False, index=True)
    requested_by = Column(String(255), nullable=True)  # account_id

    # Status lifecycle: pending -> running -> completed|failed|cancelled
    status = Column(String(32), nullable=False, default="pending")
    config = Column(JSONB, nullable=False, default=dict)
    stats = Column(JSONB, nullable=False, default=dict)
    error_message = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)

    documents = relationship("IngestionRunDocument", back_populates="run", cascade="all, delete-orphan")


class IngestionRunDocument(Base):
    """Mapping from ingestion_run -> document."""

    __tablename__ = "ingestion_run_documents"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "run_id",
            "document_id",
            name="uq_ingestion_run_documents_tenant_run_document",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)

    run_id = Column(UUID(as_uuid=True), ForeignKey("ingestion_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    document_id = Column(UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)

    source_ref = Column(String(1000), nullable=True)  # filename / URL / key
    status = Column(String(32), nullable=False, default="created")  # created|pending|processing|completed|failed|quarantined|cancelled

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    run = relationship("IngestionRun", back_populates="documents")

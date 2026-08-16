"""Document-level index channel state."""

import uuid

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

from app.core.database import Base


class DocumentIndexChannel(Base):
    """Per-document, per-pipeline index channel status."""

    __tablename__ = "document_index_channels"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "document_id",
            "pipeline_hash",
            "channel",
            name="uq_document_index_channels_identity",
        ),
        Index("ix_document_index_channels_tenant_document", "tenant_id", "document_id"),
        Index("ix_document_index_channels_tenant_dataset", "tenant_id", "dataset_id"),
        Index("ix_document_index_channels_tenant_status", "tenant_id", "status"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    dataset_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    document_id = Column(UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    pipeline_hash = Column(String(64), nullable=False)
    channel = Column(String(40), nullable=False)
    required = Column(Boolean, nullable=False, default=False)
    enabled = Column(Boolean, nullable=False, default=False)
    status = Column(String(20), nullable=False, default="pending", index=True)
    error = Column(Text, nullable=True)
    attempt_count = Column(Integer, nullable=False, default=0)
    last_attempted_at = Column(DateTime(timezone=True), nullable=True)
    last_succeeded_at = Column(DateTime(timezone=True), nullable=True)
    last_failed_at = Column(DateTime(timezone=True), nullable=True)
    last_status_changed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

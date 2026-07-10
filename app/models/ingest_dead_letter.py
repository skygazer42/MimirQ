
import uuid

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.sql import func

from app.core.database import Base


class IngestDeadLetter(Base):
    """Persistent dead-letter record for document ingestion failures."""

    __tablename__ = "ingest_dead_letters"
    __table_args__ = (
        Index("ix_ingest_dead_letters_tenant_status", "tenant_id", "status"),
        Index("ix_ingest_dead_letters_tenant_document_status", "tenant_id", "document_id", "status"),
        Index("ix_ingest_dead_letters_tenant_error_code", "tenant_id", "error_code"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    dataset_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    document_id = Column(UUID(as_uuid=True), ForeignKey("documents.id", ondelete="SET NULL"), nullable=True, index=True)

    status = Column(String(20), nullable=False, default="open")  # open | replayed | resolved
    failed_stage = Column(String(50), nullable=False, default="unknown")
    error_code = Column(String(100), nullable=False, default="ingest_failed")
    error_message = Column(Text, nullable=True)

    source_ref = Column(String(1000), nullable=True)
    original_payload = Column(JSONB, nullable=False, default=dict)
    retry_count = Column(Integer, nullable=False, default=0)

    producer_service = Column(String(80), nullable=False, default="document_processor")
    schema_version = Column(String(40), nullable=False, default="mimirq.ingest_dead_letter.v1")

    first_failed_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    last_attempt_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    replayed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

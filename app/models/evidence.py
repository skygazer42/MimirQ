"""
EvidenceSuite / EvidenceItem persistence for enterprise-grade retrieval evaluation.

Purpose:
- Persist ground-truth evidence assets (query + human-selected reference_sources)
- Support multi-stage approvals (draft -> reviewed -> approved -> archived)
- Enable reproducible retrieval audits and sync into RAGAS regression cases
"""

import uuid

from sqlalchemy import Column, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.core.database import Base


class EvidenceSuite(Base):
    """
    A dataset-scoped collection of evidence items (ground truth).

    Notes:
    - dataset_id is required so suites are isolated per knowledge base.
    - archived_at is preferred over hard delete for auditability.
    """

    __tablename__ = "evidence_suites"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    dataset_id = Column(UUID(as_uuid=True), nullable=False, index=True)

    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    tags = Column(JSONB, default=list)
    # Optional: default retrieval config snapshot (used as a UI hint; not enforced).
    config = Column(JSONB, default=dict)

    created_by = Column(String(255), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    archived_at = Column(DateTime(timezone=True), nullable=True)

    items = relationship(
        "EvidenceItem",
        back_populates="suite",
        cascade="all, delete-orphan",
    )


class EvidenceItem(Base):
    """
    A single evidence record: query + selected reference_sources.

    The `reference_sources` schema intentionally mirrors RAGAS regression case evidence pointers.
    """

    __tablename__ = "evidence_items"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    dataset_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    suite_id = Column(
        UUID(as_uuid=True), ForeignKey("evidence_suites.id", ondelete="CASCADE"), nullable=False, index=True
    )

    status = Column(String(20), nullable=False, default="draft", index=True)  # draft|reviewed|approved|archived

    query = Column(Text, nullable=False)
    expected_answer = Column(Text, nullable=True)
    tags = Column(JSONB, default=list, nullable=False)
    source_metadata = Column(JSONB, default=dict, nullable=False)
    reference_sources = Column(JSONB, default=list, nullable=False)

    # Best-effort reproducibility snapshot (retrieval preview output + metrics).
    retrieval_snapshot = Column(JSONB, default=dict)
    rag_config_snapshot = Column(JSONB, default=dict)
    notes = Column(Text, nullable=True)

    regression_case_id = Column(UUID(as_uuid=True), nullable=True, index=True)

    created_by = Column(String(255), nullable=True, index=True)
    reviewed_by = Column(String(255), nullable=True, index=True)
    approved_by = Column(String(255), nullable=True, index=True)
    archived_by = Column(String(255), nullable=True, index=True)

    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    approved_at = Column(DateTime(timezone=True), nullable=True)
    archived_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    suite = relationship("EvidenceSuite", back_populates="items")

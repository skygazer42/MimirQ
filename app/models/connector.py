"""
Connector models (enterprise-style ingestion framework).

This module introduces a minimal "connector run" abstraction:
- A connector run represents one ingestion/sync execution (e.g., URL batch import).
- Each run can create one or more documents.

The initial implementation focuses on:
- Observability (run status/stats/error)
- Extensibility (connector_id + config JSON)
"""


import uuid

from sqlalchemy import Column, DateTime, ForeignKey, ForeignKeyConstraint, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.core.database import Base


class ConnectorRun(Base):
    """Connector ingestion run."""

    __tablename__ = "connector_runs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "dataset_id"],
            ["datasets.tenant_id", "datasets.id"],
            name="fk_connector_runs_tenant_dataset",
            ondelete="CASCADE",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    dataset_id = Column(UUID(as_uuid=True), nullable=True, index=True)

    connector_id = Column(String(80), nullable=False, index=True)  # e.g., "url_batch"
    requested_by = Column(String(255), nullable=True)  # account_id

    status = Column(String(32), nullable=False, default="pending")  # pending|running|completed|failed|cancelled
    config = Column(JSONB, nullable=False, default=dict)
    stats = Column(JSONB, nullable=False, default=dict)
    error_message = Column(Text, nullable=True)

    # Optional task identifier when executed via queue.
    task_id = Column(String(255), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)

    documents = relationship("ConnectorRunDocument", back_populates="run", cascade="all, delete-orphan")


class ConnectorRunDocument(Base):
    """Mapping from connector run -> created document."""

    __tablename__ = "connector_run_documents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)

    run_id = Column(UUID(as_uuid=True), ForeignKey("connector_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    document_id = Column(UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)

    source_ref = Column(String(1000), nullable=True)  # e.g., URL
    status = Column(String(32), nullable=False, default="created")  # created|processed|failed

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    run = relationship("ConnectorRun", back_populates="documents")

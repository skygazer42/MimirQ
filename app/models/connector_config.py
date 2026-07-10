"""
Connector configuration model.

Connector runs (app.models.connector) represent individual ingestion executions.
Connector configs represent saved, reusable connector definitions per dataset.
"""


import uuid

from sqlalchemy import Boolean, Column, DateTime, ForeignKeyConstraint, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.sql import func

from app.core.database import Base


class ConnectorConfig(Base):
    """Saved connector configuration (per dataset)."""

    __tablename__ = "connector_configs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "dataset_id"],
            ["datasets.tenant_id", "datasets.id"],
            name="fk_connector_configs_tenant_dataset",
            ondelete="CASCADE",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    dataset_id = Column(UUID(as_uuid=True), nullable=False, index=True)

    connector_id = Column(String(80), nullable=False, index=True)  # e.g., "url_batch", "web_crawl"
    name = Column(String(255), nullable=False)
    enabled = Column(Boolean, nullable=False, default=True)
    schedule_cron = Column(String(64), nullable=True)

    # Connector-specific config/state payloads (validated/normalized in API layer).
    config = Column(JSONB, nullable=False, default=dict)
    state = Column(JSONB, nullable=False, default=dict)

    last_run_at = Column(DateTime(timezone=True), nullable=True)
    last_error = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

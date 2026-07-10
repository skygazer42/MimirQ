"""
Chunk preset database model.

Chunk presets are tenant-scoped templates for chunking configuration used by the
chunk preview UI and ingestion tuning workflows.
"""


import uuid

from sqlalchemy import Column, DateTime, ForeignKeyConstraint, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.sql import func

from app.core.database import Base


class ChunkPreset(Base):
    __tablename__ = "chunk_presets"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    dataset_id = Column(UUID(as_uuid=True), nullable=True, index=True)

    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)

    # Stored as a declarative payload (no executable code).
    payload = Column(JSONB, default=dict)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("ix_chunk_presets_tenant_name", "tenant_id", "name"),
        # Optional dataset scoping (governance): ensure dataset_id belongs to the same tenant.
        ForeignKeyConstraint(
            ["tenant_id", "dataset_id"],
            ["datasets.tenant_id", "datasets.id"],
            name="fk_chunk_presets_tenant_dataset",
        ),
    )

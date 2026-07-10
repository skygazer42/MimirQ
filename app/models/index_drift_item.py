
import uuid

from sqlalchemy import JSON, Column, DateTime, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

from app.core.database import Base


class IndexDriftItem(Base):
    __tablename__ = "index_drift_items"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    dataset_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    document_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    chunk_id = Column(UUID(as_uuid=True), nullable=True, index=True)

    operation = Column(String(80), nullable=False, index=True)
    channel = Column(String(40), nullable=False, index=True)
    strictness = Column(String(20), nullable=False, default="off")
    status = Column(String(20), nullable=False, default="open", index=True)

    reason = Column(String(240), nullable=False)
    details = Column(JSON, nullable=False, default=dict)
    marker = Column(JSON, nullable=False, default=dict)

    reconcile_task_id = Column(String(255), nullable=True)
    replay_count = Column(Integer, nullable=False, default=0)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    last_replayed_at = Column(DateTime(timezone=True), nullable=True)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    resolved_by = Column(String(255), nullable=True)
    resolution_note = Column(Text, nullable=True)

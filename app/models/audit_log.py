"""
Audit log models (compliance / debugging).

Keep audit records small and PII-minimal by default; callers should avoid storing raw
questions/content in `details` unless explicitly required and compliant.
"""


import uuid

from sqlalchemy import Column, DateTime, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.sql import func

from app.core.database import Base


class AuditLog(Base):
    """Append-only audit log entry (multi-tenant)."""

    __tablename__ = "audit_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)

    actor_id = Column(String(255), nullable=True, index=True)
    action = Column(String(128), nullable=False, index=True)

    resource_type = Column(String(64), nullable=True, index=True)
    resource_id = Column(String(255), nullable=True, index=True)

    request_id = Column(String(128), nullable=True, index=True)
    ip = Column(String(64), nullable=True)
    user_agent = Column(String(512), nullable=True)

    details = Column(JSONB, default=dict)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)


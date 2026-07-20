"""
Multi-tenant data models.

Defines tenant and member tables for tenant isolation.
"""
import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, Column, DateTime, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

from app.core.database import Base


class Tenant(Base):
    """Tenant table."""
    __tablename__ = "tenants"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False, unique=True)
    status = Column(String(32), default="active")
    plan = Column(String(64), default="basic")
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )


class TenantMember(Base):
    """Tenant member (placeholder; extend when user system exists)."""
    __tablename__ = "tenant_members"
    __table_args__ = (UniqueConstraint("tenant_id", "user_id", name="uq_tenant_members_tenant_user"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    # No user system yet; reserve user_id/external_id as placeholders.
    user_id = Column(String(255), nullable=True)
    role = Column(String(32), default="owner")
    # Enterprise lifecycle: allow deprovisioning without hard-deleting membership rows.
    is_active = Column(Boolean, default=True)
    is_current = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

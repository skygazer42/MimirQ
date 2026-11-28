"""SQLAlchemy identity workspaces entities."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKeyConstraint, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.infrastructure.database.connection import Base


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
    """Tenant membership for a local account or external identity."""

    __tablename__ = "tenant_members"
    __table_args__ = (UniqueConstraint("tenant_id", "user_id", name="uq_tenant_members_tenant_user"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    # Store local account IDs and external subjects in the same string column.
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


class TenantGroup(Base):
    __tablename__ = "tenant_groups"
    __table_args__ = (
        # Required for composite FKs: (tenant_id, group_id) -> tenant_groups(tenant_id, id)
        UniqueConstraint("tenant_id", "id", name="uq_tenant_groups_tenant_id_id"),
        UniqueConstraint("tenant_id", "name", name="uq_tenant_groups_tenant_name"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    name = Column(String(255), nullable=False)

    # Optional stable identifier from an external IdP (OIDC/SCIM).
    external_id = Column(String(255), nullable=True)

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    members = relationship("TenantGroupMember", back_populates="group", cascade="all, delete-orphan")


class TenantGroupMember(Base):
    __tablename__ = "tenant_group_members"
    __table_args__ = (
        UniqueConstraint("tenant_id", "group_id", "user_id", name="uq_tenant_group_members_group_user"),
        ForeignKeyConstraint(
            ["tenant_id", "group_id"],
            ["tenant_groups.tenant_id", "tenant_groups.id"],
            name="fk_tenant_group_members_tenant_group",
            ondelete="CASCADE",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    group_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    user_id = Column(String(255), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC))

    group = relationship("TenantGroup", back_populates="members")

"""
Tenant groups (enterprise directory primitive).

Motivation:
- MimirQ currently supports dataset/doc ACL allowlists by member id only.
- Top-tier enterprise deployments typically need group-based access control and
  IdP-driven provisioning (OIDC group claims / SCIM).

This module introduces the storage primitives for tenant-scoped groups and
their memberships. Group-based permissions are implemented via separate
permission tables (see follow-up migrations/models).
"""


import uuid
from datetime import UTC, datetime

from sqlalchemy import Column, DateTime, ForeignKeyConstraint, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.core.database import Base


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

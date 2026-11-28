"""SQLAlchemy documents access entities."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.infrastructure.database.connection import Base


class DocumentPermission(Base):
    """Document partial member permissions (document-level ACL allowlist)."""

    __tablename__ = "document_permissions"
    __table_args__ = (UniqueConstraint("document_id", "account_id", name="uq_document_permission_member"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    document_id = Column(UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    account_id = Column(String(255), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    document = relationship("Document", back_populates="permissions")


class DocumentGroupPermission(Base):
    """Document partial group permissions (document-level ACL allowlist by group)."""

    __tablename__ = "document_group_permissions"
    __table_args__ = (
        UniqueConstraint("tenant_id", "document_id", "group_id", name="uq_document_group_permission"),
        # Match DocumentPermission pattern: reference documents by id only and enforce tenant isolation at app layer.
        ForeignKeyConstraint(
            ["tenant_id", "group_id"],
            ["tenant_groups.tenant_id", "tenant_groups.id"],
            name="fk_document_group_permissions_tenant_group",
            ondelete="CASCADE",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    document_id = Column(UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    group_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC))

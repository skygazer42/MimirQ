"""
Group-based allowlist permissions for datasets and documents.

Notes:
- Dataset/document permissions are treated as an allowlist ("partial_members") mode.
- Group membership is stored separately (tenant_groups / tenant_group_members).
"""


import uuid
from datetime import UTC, datetime

from sqlalchemy import Column, DateTime, ForeignKey, ForeignKeyConstraint, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

from app.core.database import Base


class DatasetGroupPermission(Base):
    """Dataset partial group permissions (tenant-scoped)."""

    __tablename__ = "dataset_group_permissions"
    __table_args__ = (
        UniqueConstraint("tenant_id", "dataset_id", "group_id", name="uq_dataset_group_permission"),
        ForeignKeyConstraint(
            ["tenant_id", "dataset_id"],
            ["datasets.tenant_id", "datasets.id"],
            name="fk_dataset_group_permissions_tenant_dataset",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "group_id"],
            ["tenant_groups.tenant_id", "tenant_groups.id"],
            name="fk_dataset_group_permissions_tenant_group",
            ondelete="CASCADE",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    dataset_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    group_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


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

"""
Knowledge base data models and permission management.

Defines dataset tables and permission relationships.
"""
import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import Column, DateTime, Enum, ForeignKeyConstraint, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from app.core.database import Base


class DatasetPermissionEnum(str, enum.Enum):
    ONLY_ME = "only_me"
    ALL_TEAM_MEMBERS = "all_team_members"
    PARTIAL_MEMBERS = "partial_members"


class Dataset(Base):
    """Knowledge base / dataset"""
    __tablename__ = "datasets"
    __table_args__ = (
        # Required for composite FKs: (tenant_id, dataset_id) -> datasets(tenant_id, id).
        UniqueConstraint("tenant_id", "id", name="uq_datasets_tenant_id_id"),
        # Avoid confusing duplicates within a tenant.
        UniqueConstraint("tenant_id", "name", name="uq_datasets_tenant_name"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    description = Column(String(1024), nullable=True)
    permission = Column(Enum(DatasetPermissionEnum), nullable=False, default=DatasetPermissionEnum.ALL_TEAM_MEMBERS)
    owner_id = Column(String(255), nullable=True)  # account/user id
    # Dataset-level metadata (e.g., pipeline/governance defaults for documents).
    # Use a non-reserved attribute name; the column name remains "metadata".
    dataset_metadata = Column("metadata", JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    # relationships
    permissions = relationship("DatasetPermission", back_populates="dataset", cascade="all, delete-orphan")


class DatasetPermission(Base):
    """Dataset partial member permissions"""
    __tablename__ = "dataset_permissions"
    __table_args__ = (
        UniqueConstraint("tenant_id", "dataset_id", "account_id", name="uq_dataset_permission_member"),
        ForeignKeyConstraint(
            ["tenant_id", "dataset_id"],
            ["datasets.tenant_id", "datasets.id"],
            name="fk_dataset_permissions_tenant_dataset",
            ondelete="CASCADE",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    dataset_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    account_id = Column(String(255), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC))

    dataset = relationship("Dataset", back_populates="permissions")

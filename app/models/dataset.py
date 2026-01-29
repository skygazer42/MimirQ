"""
Knowledge base data models and permission management.

Defines dataset tables and permission relationships.
"""
import enum
import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, Enum, ForeignKey, String, UniqueConstraint
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

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    description = Column(String(1024), nullable=True)
    permission = Column(Enum(DatasetPermissionEnum), nullable=False, default=DatasetPermissionEnum.ALL_TEAM_MEMBERS)
    owner_id = Column(String(255), nullable=True)  # account/user id
    # Dataset-level metadata (e.g., pipeline/governance defaults for documents).
    # Use a non-reserved attribute name; the column name remains "metadata".
    dataset_metadata = Column("metadata", JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    # relationships
    permissions = relationship("DatasetPermission", back_populates="dataset", cascade="all, delete-orphan")


class DatasetPermission(Base):
    """Dataset partial member permissions"""
    __tablename__ = "dataset_permissions"
    __table_args__ = (
        UniqueConstraint("dataset_id", "account_id", name="uq_dataset_permission_member"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    dataset_id = Column(UUID(as_uuid=True), ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False, index=True)
    account_id = Column(String(255), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)

    dataset = relationship("Dataset", back_populates="permissions")

"""
Dataset category tree models.

These categories are tenant-scoped and allow attaching datasets to one or more
categories (many-to-many).
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import Column, DateTime, ForeignKeyConstraint, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.core.database import Base


class DatasetCategory(Base):
    __tablename__ = "dataset_categories"
    __table_args__ = (
        # Required for composite FKs: (tenant_id, category_id) -> dataset_categories(tenant_id, id).
        UniqueConstraint("tenant_id", "id", name="uq_dataset_categories_tenant_id_id"),
        # Keep sibling names unique (per tenant + parent) to avoid confusing trees.
        UniqueConstraint("tenant_id", "parent_id", "name", name="uq_dataset_categories_tenant_parent_name"),
        # Enforce tenant-safe parent linkage.
        ForeignKeyConstraint(
            ["tenant_id", "parent_id"],
            ["dataset_categories.tenant_id", "dataset_categories.id"],
            name="fk_dataset_categories_tenant_parent",
            ondelete="CASCADE",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)

    name = Column(String(255), nullable=False)
    parent_id = Column(UUID(as_uuid=True), nullable=True, index=True)

    # Optional stable ordering among siblings.
    sort_order = Column(Integer, nullable=False, default=0)

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    parent = relationship(
        "DatasetCategory",
        remote_side=[id, tenant_id],
        back_populates="children",
        foreign_keys=[tenant_id, parent_id],
    )
    children = relationship(
        "DatasetCategory",
        back_populates="parent",
        cascade="all, delete-orphan",
        foreign_keys=[tenant_id, parent_id],
    )

    memberships = relationship("DatasetCategoryMembership", back_populates="category", cascade="all, delete-orphan")


class DatasetCategoryMembership(Base):
    __tablename__ = "dataset_category_memberships"
    __table_args__ = (
        UniqueConstraint("tenant_id", "dataset_id", "category_id", name="uq_dataset_category_membership"),
        ForeignKeyConstraint(
            ["tenant_id", "dataset_id"],
            ["datasets.tenant_id", "datasets.id"],
            name="fk_dataset_category_memberships_tenant_dataset",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "category_id"],
            ["dataset_categories.tenant_id", "dataset_categories.id"],
            name="fk_dataset_category_memberships_tenant_category",
            ondelete="CASCADE",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)

    dataset_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    category_id = Column(UUID(as_uuid=True), nullable=False, index=True)

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC))

    dataset = relationship("Dataset", foreign_keys=[tenant_id, dataset_id], overlaps="memberships")
    category = relationship("DatasetCategory", back_populates="memberships", foreign_keys=[tenant_id, category_id], overlaps="dataset")

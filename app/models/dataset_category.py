"""
Dataset category tree models.

These categories are tenant-scoped and allow attaching datasets to one or more
categories (many-to-many).
"""

import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.core.database import Base


class DatasetCategory(Base):
    __tablename__ = "dataset_categories"
    __table_args__ = (
        # Keep sibling names unique (per tenant + parent) to avoid confusing trees.
        UniqueConstraint("tenant_id", "parent_id", "name", name="uq_dataset_categories_tenant_parent_name"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)

    name = Column(String(255), nullable=False)
    parent_id = Column(UUID(as_uuid=True), ForeignKey("dataset_categories.id", ondelete="CASCADE"), nullable=True, index=True)

    # Optional stable ordering among siblings.
    sort_order = Column(Integer, nullable=False, default=0)

    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    parent = relationship("DatasetCategory", remote_side=[id], back_populates="children")
    children = relationship("DatasetCategory", back_populates="parent", cascade="all, delete-orphan")

    memberships = relationship("DatasetCategoryMembership", back_populates="category", cascade="all, delete-orphan")


class DatasetCategoryMembership(Base):
    __tablename__ = "dataset_category_memberships"
    __table_args__ = (
        UniqueConstraint("tenant_id", "dataset_id", "category_id", name="uq_dataset_category_membership"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)

    dataset_id = Column(UUID(as_uuid=True), ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False, index=True)
    category_id = Column(UUID(as_uuid=True), ForeignKey("dataset_categories.id", ondelete="CASCADE"), nullable=False, index=True)

    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)

    dataset = relationship("Dataset")
    category = relationship("DatasetCategory", back_populates="memberships")


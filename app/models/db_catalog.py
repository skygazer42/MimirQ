"""
DB catalog models for database connectors.

These tables store:
- schema/table/column metadata for SQLServer/MySQL connectors
- safe (digest-only) profiling snapshots; no raw rows are stored here
"""


import uuid

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, ForeignKeyConstraint, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.core.database import Base


class DbCatalogTable(Base):
    """Catalog entry for a DB table or view."""

    __tablename__ = "db_catalog_tables"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "dataset_id"],
            ["datasets.tenant_id", "datasets.id"],
            name="fk_db_catalog_tables_tenant_dataset",
            ondelete="CASCADE",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    dataset_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    connector_config_id = Column(
        UUID(as_uuid=True),
        ForeignKey("connector_configs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    engine = Column(String(32), nullable=False, index=True)  # mysql|sqlserver
    db_name = Column(String(255), nullable=False, index=True)
    schema_name = Column(String(255), nullable=True, index=True)
    table_name = Column(String(255), nullable=False, index=True)
    table_type = Column(String(32), nullable=False, default="table")  # table|view
    comment = Column(Text, nullable=True)
    fingerprint = Column(String(80), nullable=False, index=True)

    last_seen_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    columns = relationship("DbCatalogColumn", back_populates="table", cascade="all, delete-orphan")
    profiles = relationship("DbProfileSnapshot", back_populates="table", cascade="all, delete-orphan")


class DbCatalogColumn(Base):
    """Column metadata for a catalog table."""

    __tablename__ = "db_catalog_columns"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    table_id = Column(
        UUID(as_uuid=True),
        ForeignKey("db_catalog_tables.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    ordinal = Column(Integer, nullable=False, default=0)
    name = Column(String(255), nullable=False, index=True)
    data_type = Column(String(255), nullable=True)
    nullable = Column(Boolean, nullable=True)
    comment = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    table = relationship("DbCatalogTable", back_populates="columns")


class DbProfileSnapshot(Base):
    """Safe aggregate profiling results for a table (per entitlement)."""

    __tablename__ = "db_profile_snapshots"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    table_id = Column(
        UUID(as_uuid=True),
        ForeignKey("db_catalog_tables.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    entitlement_hash = Column(String(255), nullable=False, index=True)
    profile = Column(JSONB, nullable=False, default=dict)
    sample_meta = Column(JSONB, nullable=False, default=dict)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    table = relationship("DbCatalogTable", back_populates="profiles")

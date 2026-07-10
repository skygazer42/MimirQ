"""
DB catalog API schemas.

These schemas cover read-only metadata and safe, aggregate profiling snapshots
for SQLServer/MySQL catalog connectors.
"""


from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from app.api.schemas.base import OrmModel, OrmTimestampModel


class DbCatalogColumnOut(OrmModel):
    id: UUID
    table_id: UUID
    ordinal: int = 0
    name: str
    data_type: str | None = None
    nullable: bool | None = None
    comment: str | None = None
    created_at: datetime


class DbCatalogTableSummaryOut(OrmTimestampModel):
    id: UUID
    connector_config_id: UUID | None = None
    engine: str
    db_name: str
    schema_name: str | None = None
    table_name: str
    table_type: str
    comment: str | None = None
    fingerprint: str
    last_seen_at: datetime | None = None


class DbCatalogTableDetailOut(DbCatalogTableSummaryOut):
    columns: list[DbCatalogColumnOut] = Field(default_factory=list)


class DbCatalogTablesListResponse(BaseModel):
    total: int
    items: list[DbCatalogTableSummaryOut]


class DbProfileSnapshotOut(OrmModel):
    id: UUID
    table_id: UUID
    entitlement_hash: str
    profile: dict[str, Any] = Field(default_factory=dict)
    sample_meta: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class DbProfileSnapshotListResponse(BaseModel):
    total: int
    items: list[DbProfileSnapshotOut]


"""
DB catalog API schemas.

These schemas cover read-only metadata and safe, aggregate profiling snapshots
for SQLServer/MySQL catalog connectors.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field

from app.api.schemas.base import OrmModel, OrmTimestampModel


class DbCatalogColumnOut(OrmModel):
    id: UUID
    table_id: UUID
    ordinal: int = 0
    name: str
    data_type: Optional[str] = None
    nullable: Optional[bool] = None
    comment: Optional[str] = None
    created_at: datetime


class DbCatalogTableSummaryOut(OrmTimestampModel):
    id: UUID
    connector_config_id: Optional[UUID] = None
    engine: str
    db_name: str
    schema_name: Optional[str] = None
    table_name: str
    table_type: str
    comment: Optional[str] = None
    fingerprint: str
    last_seen_at: Optional[datetime] = None


class DbCatalogTableDetailOut(DbCatalogTableSummaryOut):
    columns: List[DbCatalogColumnOut] = Field(default_factory=list)


class DbCatalogTablesListResponse(BaseModel):
    total: int
    items: List[DbCatalogTableSummaryOut]


class DbProfileSnapshotOut(OrmModel):
    id: UUID
    table_id: UUID
    entitlement_hash: str
    profile: Dict[str, Any] = Field(default_factory=dict)
    sample_meta: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class DbProfileSnapshotListResponse(BaseModel):
    total: int
    items: List[DbProfileSnapshotOut]


"""Audit log query, export and lifecycle request/response schemas."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.api.schemas.base import OrmModel


class AuditLogOut(OrmModel):
    id: UUID
    tenant_id: UUID
    actor_id: str | None = None
    action: str
    resource_type: str | None = None
    resource_id: str | None = None
    request_id: str | None = None
    ip: str | None = None
    user_agent: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class AuditLogListResponse(BaseModel):
    total: int
    items: list[AuditLogOut]


class AuditLogPurgeResponse(BaseModel):
    dry_run: bool = True
    scope: str = "retention"
    retention_days: int
    cutoff: datetime
    max_delete: int
    eligible: int
    deleted: int
    filters: dict[str, Any] = Field(default_factory=dict)


class AuditLogDeleteRequest(BaseModel):
    ids: list[UUID] = Field(min_length=1, max_length=500)


class AuditLogDeleteResponse(BaseModel):
    requested: int
    deleted: int
    missing: int
    ids: list[UUID]


class AuditLogFilterParams(BaseModel):
    actor_id: str | None = Field(default=None, max_length=255)
    action: str | None = Field(default=None, max_length=128)
    resource_type: str | None = Field(default=None, max_length=64)
    resource_id: str | None = Field(default=None, max_length=255)
    request_id: str | None = Field(default=None, max_length=128)
    since: datetime | None = None
    until: datetime | None = None


class AuditLogExportParams(AuditLogFilterParams):
    limit: int = Field(default=1000, ge=1, le=10_000)
    after_created_at: datetime | None = Field(default=None, description="Cursor: last seen created_at")
    after_id: UUID | None = Field(default=None, description="Cursor: last seen id (tie-breaker)")
    include_sensitive: bool = Field(default=False, description="Include sensitive detail keys")
    gzip: bool = Field(default=False, description="Return gzip-compressed NDJSON")


class AuditLogPurgeParams(AuditLogFilterParams):
    retention_days: int = Field(default=90, ge=1, le=3650, description="Delete logs older than N days")
    max_delete: int = Field(default=100_000, ge=1, le=1_000_000, description="Max rows to delete")
    dry_run: bool = True
    purge_scope: Literal["retention", "filtered"] = Field(
        default="retention",
        description="retention=older than N days; filtered=current explicit filters",
    )

"""Audit log query, export and lifecycle request/response schemas."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class AuditLogOut(BaseModel):
    id: UUID
    tenant_id: UUID
    actor_id: str | None = None
    action: str
    resource_type: str | None = None
    resource_id: str | None = None
    request_id: str | None = None
    ip: str | None = None
    user_agent: str | None = None
    details: dict[str, Any] = {}
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


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
    ids: list[UUID] = Field(..., min_length=1, max_length=500)


class AuditLogDeleteResponse(BaseModel):
    requested: int
    deleted: int
    missing: int
    ids: list[UUID]


class AuditLogFilterParams(BaseModel):
    actor_id: str | None = None
    action: str | None = None
    resource_type: str | None = None
    resource_id: str | None = None
    request_id: str | None = None
    since: datetime | None = None
    until: datetime | None = None


class AuditLogExportParams(BaseModel):
    limit: int = 1000
    after_created_at: datetime | None = None
    after_id: UUID | None = None
    include_sensitive: bool = False
    gzip: bool = False


class AuditLogPurgeParams(BaseModel):
    retention_days: int = 90
    max_delete: int = 100_000
    dry_run: bool = True
    purge_scope: Literal["retention", "filtered"] = "retention"

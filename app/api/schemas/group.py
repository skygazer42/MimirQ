"""
Tenant groups API schemas.

Groups are tenant-scoped and are intended to support enterprise directory needs:
- group-based dataset/doc access allowlists
- optional IdP-driven provisioning (OIDC group claims / SCIM)
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from app.api.schemas.base import OrmTimestampModel


class TenantGroupOut(OrmTimestampModel):
    id: UUID
    tenant_id: UUID
    name: str
    external_id: str | None = None


class TenantGroupListResponse(BaseModel):
    total: int
    items: list[TenantGroupOut]


class TenantGroupCreateRequest(BaseModel):
    name: str = Field(..., max_length=255)
    external_id: str | None = Field(default=None, max_length=255)

    @model_validator(mode="after")
    def _normalize(self) -> "TenantGroupCreateRequest":
        self.name = self.name.strip()
        if not self.name:
            raise ValueError("name is required")
        if self.external_id is not None:
            self.external_id = self.external_id.strip()
        return self


class TenantGroupUpdateRequest(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    external_id: str | None = Field(default=None, max_length=255)

    @model_validator(mode="after")
    def _normalize(self) -> "TenantGroupUpdateRequest":
        if self.name is not None:
            self.name = self.name.strip()
        if self.external_id is not None:
            self.external_id = self.external_id.strip()
        return self


class TenantGroupMemberOut(BaseModel):
    user_id: str
    created_at: datetime


class TenantGroupMemberListResponse(BaseModel):
    total: int
    items: list[TenantGroupMemberOut]


class TenantGroupMembersUpdateRequest(BaseModel):
    member_ids: list[str] = Field(default_factory=list, max_length=200)

    @model_validator(mode="after")
    def _normalize(self) -> "TenantGroupMembersUpdateRequest":
        seen: set[str] = set()
        out: list[str] = []
        for raw in self.member_ids:
            member_id = raw.strip()
            if not member_id or member_id in seen:
                continue
            seen.add(member_id)
            if len(member_id) > 255:
                raise ValueError("member id too long (max=255)")
            out.append(member_id)
        self.member_ids = out
        return self


class TenantGroupMembersUpdateResponse(BaseModel):
    updated: int

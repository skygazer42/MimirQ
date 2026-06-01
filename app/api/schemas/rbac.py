from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.constants import UserRoles

_TENANT_ROLE_DESCRIPTION = "owner|admin|auditor|editor|dataset_operator|viewer"


class TenantMemberOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    user_id: str | None = None
    role: str = Field(default=UserRoles.VIEWER, description=_TENANT_ROLE_DESCRIPTION)
    is_active: bool = True
    is_current: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None


class TenantMemberListResponse(BaseModel):
    total: int = 0
    items: list[TenantMemberOut] = Field(default_factory=list)


class TenantMemberDeleteResponse(BaseModel):
    user_id: str
    removed: bool = True
    revoked_group_memberships: int = 0
    revoked_dataset_permissions: int = 0
    revoked_document_permissions: int = 0


class TenantAccessOut(BaseModel):
    tenant_id: UUID
    account_id: str
    role: str = Field(default=UserRoles.VIEWER, description=_TENANT_ROLE_DESCRIPTION)
    permissions: list[str] = Field(default_factory=list)
    navigation_user_visible_modules: list[str] = Field(default_factory=list)
    is_active: bool = True
    is_current: bool = False


class TenantMemberUpdateRequest(BaseModel):
    role: str = Field(..., description=_TENANT_ROLE_DESCRIPTION)

    @field_validator("role", mode="before")
    @classmethod
    def _normalize_role(cls, v):  # noqa: ANN001
        return str(v or "").strip().lower()

    @field_validator("role")
    @classmethod
    def _validate_role(cls, v: str) -> str:
        allowed = {
            UserRoles.OWNER,
            UserRoles.ADMIN,
            UserRoles.AUDITOR,
            UserRoles.EDITOR,
            UserRoles.DATASET_OPERATOR,
            UserRoles.VIEWER,
        }
        if v not in allowed:
            raise ValueError(f"role must be one of: {', '.join(sorted(allowed))}")
        return v

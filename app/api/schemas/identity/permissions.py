from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.api.schemas.base import OrmModel
from app.core.constants import UserRoles

_TENANT_ROLE_DESCRIPTION = "owner|admin|auditor|editor|dataset_operator|viewer"


class TenantMemberListQuery(BaseModel):
    skip: int = Field(default=0, ge=0)
    limit: int = Field(default=200, ge=1, le=1000)


class TenantMemberOut(OrmModel):
    id: UUID
    tenant_id: UUID
    user_id: str
    username: str | None
    email: str | None
    role: str = Field(default=UserRoles.VIEWER, description=_TENANT_ROLE_DESCRIPTION)
    is_active: bool = True
    is_current: bool = False
    created_at: datetime
    updated_at: datetime


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
    role: str = Field(description=_TENANT_ROLE_DESCRIPTION)

    @field_validator("role", mode="after")
    @classmethod
    def _validate_role(cls, value: str) -> str:
        value = value.strip().lower()
        allowed = {
            UserRoles.OWNER,
            UserRoles.ADMIN,
            UserRoles.AUDITOR,
            UserRoles.EDITOR,
            UserRoles.DATASET_OPERATOR,
            UserRoles.VIEWER,
        }
        if value not in allowed:
            raise ValueError(f"role must be one of: {', '.join(sorted(allowed))}")
        return value

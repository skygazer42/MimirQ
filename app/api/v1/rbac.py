"""
RBAC admin API (tenant-scoped).

Notes:
- MimirQ currently models roles on `tenant_members.role` (tenant-scoped).
- Dataset/connector write APIs already gate on EDIT_ROLES derived from this field.
- This router provides a small admin surface to view/update member roles.
"""


from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.api.schemas.rbac import (
    TenantAccessOut,
    TenantMemberDeleteResponse,
    TenantMemberListResponse,
    TenantMemberOut,
    TenantMemberUpdateRequest,
)
from app.core.config import settings
from app.core.constants import UserRoles
from app.core.database import get_db
from app.models.dataset import DatasetPermission
from app.models.document import DocumentPermission
from app.models.tenant import TenantMember
from app.models.tenant_group import TenantGroupMember
from app.services.audit_log_service import audit_log_event
from app.services.dataset_service import DatasetService
from app.services.navigation_visibility import navigation_user_visible_modules_from_settings
from app.services.rbac_service import TenantPermissions, all_tenant_permissions, ensure_tenant_permission, role_allows

_DEFAULT_HTTP_EXCEPTION_RESPONSES = {
    400: {"description": "Bad Request"},
    403: {"description": "Forbidden"},
    404: {"description": "Not Found"},
    409: {"description": "Conflict"},
    416: {"description": "Range Not Satisfiable"},
}

router = APIRouter(responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)


def _lock_active_admin_members(db: Session, tenant_id: UUID) -> list[TenantMember]:
    return (
        db.query(TenantMember)
        .filter(
            TenantMember.tenant_id == tenant_id,
            TenantMember.is_active.is_(True),
            TenantMember.role.in_(list(UserRoles.ADMIN_ROLES)),
        )
        .order_by(TenantMember.id.asc())
        .with_for_update()
        .all()
    )


@router.get("/me", response_model=TenantAccessOut, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def get_current_tenant_access(
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    member = DatasetService.ensure_member(db, tenant_id, account_id)
    role = str(getattr(member, "role", "") or "").strip().lower()
    permissions = [permission for permission in all_tenant_permissions() if role_allows(permission, role=role)]
    return TenantAccessOut(
        tenant_id=tenant_id,
        account_id=account_id,
        role=role,
        permissions=permissions,
        navigation_user_visible_modules=navigation_user_visible_modules_from_settings(settings),
        is_active=bool(getattr(member, "is_active", True)),
        is_current=bool(getattr(member, "is_current", False)),
    )


@router.get("/members", response_model=TenantMemberListResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def list_tenant_members(
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    ensure_tenant_permission(
        db,
        tenant_id,
        account_id,
        TenantPermissions.SETTINGS_READ,
        detail="No permission to view tenant members",
    )

    q = db.query(TenantMember).filter(TenantMember.tenant_id == tenant_id)
    total = int(q.count())
    items = (
        q.order_by(
            TenantMember.is_current.desc(),
            TenantMember.updated_at.desc().nullslast(),
            TenantMember.created_at.desc().nullslast(),
        )
        .offset(skip)
        .limit(limit)
        .all()
    )
    return TenantMemberListResponse(total=total, items=[TenantMemberOut.model_validate(it) for it in items])


@router.patch("/members/{user_id}", response_model=TenantMemberOut, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def patch_tenant_member_role(
    user_id: str,
    payload: TenantMemberUpdateRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    ensure_tenant_permission(
        db,
        tenant_id,
        account_id,
        TenantPermissions.SETTINGS_WRITE,
        detail="No permission to manage tenant member roles",
    )

    uid = str(user_id or "").strip()
    if not uid:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="user_id is required")

    active_admins = _lock_active_admin_members(db, tenant_id)
    member = (
        db.query(TenantMember)
        .filter(TenantMember.tenant_id == tenant_id, TenantMember.user_id == uid)
        .with_for_update()
        .first()
    )
    if not member:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant member not found")

    next_role = str(payload.role or "").strip().lower()
    current_role = str(getattr(member, "role", "") or "").strip().lower()
    if current_role in UserRoles.ADMIN_ROLES and next_role not in UserRoles.ADMIN_ROLES and len(active_admins) <= 1:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="不能降级最后一个管理员")

    member.role = next_role
    db.commit()
    db.refresh(member)
    return TenantMemberOut.model_validate(member)


@router.delete(
    "/members/{user_id}",
    response_model=TenantMemberDeleteResponse,
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
def delete_tenant_member(
    user_id: str,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    ensure_tenant_permission(
        db,
        tenant_id,
        account_id,
        TenantPermissions.SETTINGS_WRITE,
        detail="没有权限移除成员",
    )

    uid = str(user_id or "").strip()
    if not uid:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="缺少成员 ID")
    if uid == str(account_id or "").strip():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="不能移除当前用户")

    active_admins = _lock_active_admin_members(db, tenant_id)
    member = (
        db.query(TenantMember)
        .filter(TenantMember.tenant_id == tenant_id, TenantMember.user_id == uid)
        .with_for_update()
        .first()
    )
    if not member:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="找不到该成员")

    member_role = str(getattr(member, "role", "") or "").strip().lower()
    if member_role in UserRoles.ADMIN_ROLES and bool(getattr(member, "is_active", True)):
        if len(active_admins) <= 1:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="不能移除最后一个管理员")

    revoked_groups = int(
        db.query(TenantGroupMember)
        .filter(TenantGroupMember.tenant_id == tenant_id, TenantGroupMember.user_id == uid)
        .delete(synchronize_session=False)
        or 0
    )
    revoked_datasets = int(
        db.query(DatasetPermission)
        .filter(DatasetPermission.tenant_id == tenant_id, DatasetPermission.account_id == uid)
        .delete(synchronize_session=False)
        or 0
    )
    revoked_documents = int(
        db.query(DocumentPermission)
        .filter(DocumentPermission.tenant_id == tenant_id, DocumentPermission.account_id == uid)
        .delete(synchronize_session=False)
        or 0
    )
    db.delete(member)

    audit_log_event(
        db,
        tenant_id=tenant_id,
        actor_id=account_id,
        action="rbac.member.remove",
        resource_type="tenant_member",
        resource_id=uid,
        details={
            "role": member_role,
            "revoked_group_memberships": revoked_groups,
            "revoked_dataset_permissions": revoked_datasets,
            "revoked_document_permissions": revoked_documents,
        },
    )
    db.commit()

    return TenantMemberDeleteResponse(
        user_id=uid,
        removed=True,
        revoked_group_memberships=revoked_groups,
        revoked_dataset_permissions=revoked_datasets,
        revoked_document_permissions=revoked_documents,
    )

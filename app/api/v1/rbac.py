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

from app.api.dependencies import get_current_account_id, get_tenant_id
from app.api.schemas.identity import (
    TenantAccessOut,
    TenantMemberDeleteResponse,
    TenantMemberListQuery,
    TenantMemberListResponse,
    TenantMemberOut,
    TenantMemberUpdateRequest,
)
from app.api.utils import (
    DEFAULT_HTTP_EXCEPTION_RESPONSES as _DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
from app.core.config import settings
from app.core.constants import UserRoles
from app.core.database import get_db
from app.models.dataset import DatasetPermission
from app.models.document import DocumentPermission
from app.models.tenant import TenantMember
from app.models.tenant_group import TenantGroupMember
from app.models.user import User
from app.services import dataset_service
from app.services.audit_log_service import audit_log_event
from app.services.navigation_visibility import normalize_navigation_modules
from app.services.rbac_service import TenantPermissions, all_tenant_permissions, ensure_tenant_permission, role_allows

router = APIRouter(responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)


def _lock_active_admin_members(db: Session, tenant_id: UUID) -> list[TenantMember]:
    return (
        db.query(TenantMember)
        .filter(
            TenantMember.tenant_id == tenant_id,
            TenantMember.is_active.is_(True),
            TenantMember.role.in_(UserRoles.ADMIN_ROLES),
        )
        .order_by(TenantMember.id.asc())
        .with_for_update()
        .all()
    )


def _get_member_for_update(db: Session, tenant_id: UUID, user_id: str, *, detail: str) -> TenantMember:
    member = (
        db.query(TenantMember)
        .filter(TenantMember.tenant_id == tenant_id, TenantMember.user_id == user_id)
        .with_for_update()
        .first()
    )
    if member is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)
    return member


def _member_outputs(db: Session, members: list[TenantMember]) -> list[TenantMemberOut]:
    # Local IDs are UUIDs; external IdP subjects may be arbitrary strings. Batch
    # the identity lookup without casting a UUID column to database-specific text.
    local_user_ids = []
    for member in members:
        try:
            local_user_ids.append(UUID(str(member.user_id)))
        except ValueError:
            continue
    users = db.query(User).filter(User.id.in_(local_user_ids)).all() if local_user_ids else []
    users_by_id = {str(user.id): user for user in users}
    output = []
    for member in members:
        user = users_by_id.get(member.user_id)
        output.append(
            TenantMemberOut(
                id=member.id,
                tenant_id=member.tenant_id,
                user_id=member.user_id,
                username=user.username if user else None,
                email=user.email if user else None,
                role=member.role,
                is_active=member.is_active,
                is_current=member.is_current,
                created_at=member.created_at,
                updated_at=member.updated_at,
            )
        )
    return output


@router.get("/me", response_model=TenantAccessOut)
def get_current_tenant_access(
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> TenantAccessOut:
    member = dataset_service.ensure_member(db, tenant_id, account_id)
    role = member.role.strip().lower()
    permissions = [permission for permission in all_tenant_permissions() if role_allows(permission, role=role)]
    return TenantAccessOut(
        tenant_id=tenant_id,
        account_id=account_id,
        role=role,
        permissions=permissions,
        navigation_user_visible_modules=normalize_navigation_modules(settings.NAVIGATION_USER_VISIBLE_MODULES),
        is_active=bool(member.is_active),
        is_current=bool(member.is_current),
    )


@router.get("/members", response_model=TenantMemberListResponse)
def list_tenant_members(
    query: Annotated[TenantMemberListQuery, Query()],
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> TenantMemberListResponse:
    ensure_tenant_permission(
        db,
        tenant_id,
        account_id,
        TenantPermissions.SETTINGS_READ,
        detail="No permission to view tenant members",
    )

    members = db.query(TenantMember).filter(TenantMember.tenant_id == tenant_id)
    total = members.count()
    items = (
        members.order_by(
            TenantMember.is_current.desc(),
            TenantMember.updated_at.desc().nullslast(),
            TenantMember.created_at.desc().nullslast(),
        )
        .offset(query.skip)
        .limit(query.limit)
        .all()
    )
    return TenantMemberListResponse(total=total, items=_member_outputs(db, items))


@router.patch("/members/{user_id}", response_model=TenantMemberOut)
def patch_tenant_member_role(
    user_id: str,
    payload: TenantMemberUpdateRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> TenantMemberOut:
    ensure_tenant_permission(
        db,
        tenant_id,
        account_id,
        TenantPermissions.SETTINGS_WRITE,
        detail="No permission to manage tenant member roles",
    )

    user_id = user_id.strip()
    if not user_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="user_id is required")

    active_admins = _lock_active_admin_members(db, tenant_id)
    member = _get_member_for_update(db, tenant_id, user_id, detail="Tenant member not found")

    next_role = payload.role
    current_role = member.role.strip().lower()
    if current_role in UserRoles.ADMIN_ROLES and next_role not in UserRoles.ADMIN_ROLES and len(active_admins) <= 1:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="不能降级最后一个管理员")

    member.role = next_role
    db.commit()
    db.refresh(member)
    return _member_outputs(db, [member])[0]


@router.delete(
    "/members/{user_id}",
    response_model=TenantMemberDeleteResponse,
)
def delete_tenant_member(
    user_id: str,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> TenantMemberDeleteResponse:
    ensure_tenant_permission(
        db,
        tenant_id,
        account_id,
        TenantPermissions.SETTINGS_WRITE,
        detail="没有权限移除成员",
    )

    user_id = user_id.strip()
    if not user_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="缺少成员 ID")
    if user_id == account_id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="不能移除当前用户")

    active_admins = _lock_active_admin_members(db, tenant_id)
    member = _get_member_for_update(db, tenant_id, user_id, detail="找不到该成员")

    member_role = member.role.strip().lower()
    if member_role in UserRoles.ADMIN_ROLES and member.is_active and len(active_admins) <= 1:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="不能移除最后一个管理员")

    revoked_groups = (
        db.query(TenantGroupMember)
        .filter(TenantGroupMember.tenant_id == tenant_id, TenantGroupMember.user_id == user_id)
        .delete(synchronize_session=False)
    )
    revoked_datasets = (
        db.query(DatasetPermission)
        .filter(DatasetPermission.tenant_id == tenant_id, DatasetPermission.account_id == user_id)
        .delete(synchronize_session=False)
    )
    revoked_documents = (
        db.query(DocumentPermission)
        .filter(DocumentPermission.tenant_id == tenant_id, DocumentPermission.account_id == user_id)
        .delete(synchronize_session=False)
    )
    db.delete(member)

    audit_log_event(
        db,
        tenant_id=tenant_id,
        actor_id=account_id,
        action="rbac.member.remove",
        resource_type="tenant_member",
        resource_id=user_id,
        details={
            "role": member_role,
            "revoked_group_memberships": revoked_groups,
            "revoked_dataset_permissions": revoked_datasets,
            "revoked_document_permissions": revoked_documents,
        },
    )
    db.commit()

    return TenantMemberDeleteResponse(
        user_id=user_id,
        removed=True,
        revoked_group_memberships=revoked_groups,
        revoked_dataset_permissions=revoked_datasets,
        revoked_document_permissions=revoked_documents,
    )

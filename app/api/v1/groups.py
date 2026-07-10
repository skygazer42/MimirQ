"""
Tenant groups API (enterprise directory primitive).
"""


import contextlib
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.api.schemas.group import (
    TenantGroupCreateRequest,
    TenantGroupListResponse,
    TenantGroupMemberListResponse,
    TenantGroupMemberOut,
    TenantGroupMembersUpdateRequest,
    TenantGroupMembersUpdateResponse,
    TenantGroupOut,
    TenantGroupUpdateRequest,
)
from app.core.database import get_db
from app.services.audit_log_service import audit_log_event
from app.services.rbac_service import TenantPermissions, ensure_tenant_permission
from app.services.tenant_group_service import TenantGroupService

_DEFAULT_HTTP_EXCEPTION_RESPONSES = {
    400: {"description": "Bad Request"},
    403: {"description": "Forbidden"},
    404: {"description": "Not Found"},
    409: {"description": "Conflict"},
    416: {"description": "Range Not Satisfiable"},
}

router = APIRouter(responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)

_NO_PERMISSION_TO_MANAGE_GROUPS_DETAIL = "No permission to manage groups"


@router.get("/", response_model=TenantGroupListResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def list_groups(
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
        detail="No permission to view groups",
    )
    total, groups = TenantGroupService.list_groups(db, tenant_id=tenant_id, skip=skip, limit=limit)
    return TenantGroupListResponse(total=total, items=[TenantGroupOut.model_validate(g) for g in groups])


@router.post("/", response_model=TenantGroupOut, status_code=201, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def create_group(
    payload: TenantGroupCreateRequest,
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
        detail=_NO_PERMISSION_TO_MANAGE_GROUPS_DETAIL,
    )
    group = TenantGroupService.create_group(db, tenant_id=tenant_id, name=payload.name, external_id=payload.external_id)
    audit_log_event(
        db,
        tenant_id=tenant_id,
        actor_id=account_id,
        action="group.create",
        resource_type="tenant_group",
        resource_id=str(group.id),
        details={
            "name": str(getattr(group, "name", "") or "")[:255],
            "has_external_id": bool(getattr(group, "external_id", None)),
        },
    )
    with contextlib.suppress(Exception):
        db.commit()
    return TenantGroupOut.model_validate(group)


@router.get("/{group_id}", response_model=TenantGroupOut, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def get_group(
    group_id: UUID,
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
        detail="No permission to view groups",
    )
    group = TenantGroupService.get_group(db, tenant_id=tenant_id, group_id=group_id)
    return TenantGroupOut.model_validate(group)


@router.patch("/{group_id}", response_model=TenantGroupOut, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def patch_group(
    group_id: UUID,
    payload: TenantGroupUpdateRequest,
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
        detail=_NO_PERMISSION_TO_MANAGE_GROUPS_DETAIL,
    )
    group = TenantGroupService.update_group(
        db,
        tenant_id=tenant_id,
        group_id=group_id,
        name=payload.name,
        external_id=payload.external_id,
    )
    audit_log_event(
        db,
        tenant_id=tenant_id,
        actor_id=account_id,
        action="group.update",
        resource_type="tenant_group",
        resource_id=str(group_id),
        details={
            "name": str(getattr(group, "name", "") or "")[:255],
            "has_external_id": bool(getattr(group, "external_id", None)),
        },
    )
    with contextlib.suppress(Exception):
        db.commit()
    return TenantGroupOut.model_validate(group)


@router.delete("/{group_id}", status_code=204, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def delete_group(
    group_id: UUID,
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
        detail=_NO_PERMISSION_TO_MANAGE_GROUPS_DETAIL,
    )
    TenantGroupService.delete_group(db, tenant_id=tenant_id, group_id=group_id)
    audit_log_event(
        db,
        tenant_id=tenant_id,
        actor_id=account_id,
        action="group.delete",
        resource_type="tenant_group",
        resource_id=str(group_id),
        details={},
    )
    with contextlib.suppress(Exception):
        db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{group_id}/members", response_model=TenantGroupMemberListResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def list_group_members(
    group_id: UUID,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=1000)] = 500,
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
        detail="No permission to view group members",
    )
    total, rows = TenantGroupService.list_members(db, tenant_id=tenant_id, group_id=group_id, skip=skip, limit=limit)
    items = [TenantGroupMemberOut(user_id=str(r.user_id or ""), created_at=r.created_at) for r in rows]
    return TenantGroupMemberListResponse(total=total, items=items)


@router.post("/{group_id}/members", response_model=TenantGroupMembersUpdateResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def add_group_members(
    group_id: UUID,
    payload: TenantGroupMembersUpdateRequest,
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
        detail="No permission to manage group members",
    )
    added = TenantGroupService.add_members(db, tenant_id=tenant_id, group_id=group_id, member_ids=payload.member_ids)
    audit_log_event(
        db,
        tenant_id=tenant_id,
        actor_id=account_id,
        action="group.members.add",
        resource_type="tenant_group",
        resource_id=str(group_id),
        details={
            "member_count_requested": int(len(payload.member_ids or [])),
            "member_count_updated": int(added or 0),
        },
    )
    with contextlib.suppress(Exception):
        db.commit()
    return TenantGroupMembersUpdateResponse(updated=int(added))


@router.post("/{group_id}/members/remove", response_model=TenantGroupMembersUpdateResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def remove_group_members(
    group_id: UUID,
    payload: TenantGroupMembersUpdateRequest,
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
        detail="No permission to manage group members",
    )
    removed = TenantGroupService.remove_members(db, tenant_id=tenant_id, group_id=group_id, member_ids=payload.member_ids)
    audit_log_event(
        db,
        tenant_id=tenant_id,
        actor_id=account_id,
        action="group.members.remove",
        resource_type="tenant_group",
        resource_id=str(group_id),
        details={
            "member_count_requested": int(len(payload.member_ids or [])),
            "member_count_updated": int(removed or 0),
        },
    )
    with contextlib.suppress(Exception):
        db.commit()
    return TenantGroupMembersUpdateResponse(updated=int(removed))

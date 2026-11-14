"""
Tenant groups API (enterprise directory primitive).
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_account_id, get_tenant_id
from app.api.schemas.identity import (
    TenantGroupCreateRequest,
    TenantGroupListQuery,
    TenantGroupListResponse,
    TenantGroupMemberListQuery,
    TenantGroupMemberListResponse,
    TenantGroupMemberOut,
    TenantGroupMembersUpdateRequest,
    TenantGroupMembersUpdateResponse,
    TenantGroupOut,
    TenantGroupUpdateRequest,
)
from app.api.utils import DEFAULT_HTTP_EXCEPTION_RESPONSES
from app.core.database import get_db
from app.rag.core.logging import get_logger
from app.services import tenant_group_service
from app.services.audit_log_service import audit_log_event
from app.services.rbac_service import TenantPermissions, ensure_tenant_permission

router = APIRouter(responses=DEFAULT_HTTP_EXCEPTION_RESPONSES)
logger = get_logger(__name__)

_NO_PERMISSION_TO_MANAGE_GROUPS_DETAIL = "No permission to manage groups"


def _commit_group_audit(
    db: Session,
    *,
    tenant_id: UUID,
    account_id: str,
    action: str,
    group_id: UUID,
    details: dict[str, object],
) -> None:
    """Commit the audit sidecar after the service has committed the group change."""
    try:
        audit_log_event(
            db,
            tenant_id=tenant_id,
            actor_id=account_id,
            action=action,
            resource_type="tenant_group",
            resource_id=str(group_id),
            details=details,
        )
        db.commit()
    except Exception:
        logger.warning(
            "Group operation committed but audit logging failed: action=%s group_id=%s",
            action,
            group_id,
            exc_info=True,
        )
        db.rollback()


@router.get("/", response_model=TenantGroupListResponse)
def list_groups(
    query: Annotated[TenantGroupListQuery, Query()],
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> TenantGroupListResponse:
    ensure_tenant_permission(
        db,
        tenant_id,
        account_id,
        TenantPermissions.SETTINGS_READ,
        detail="No permission to view groups",
    )
    total, groups = tenant_group_service.list_groups(db, tenant_id=tenant_id, skip=query.skip, limit=query.limit)
    return TenantGroupListResponse(total=total, items=[TenantGroupOut.model_validate(group) for group in groups])


@router.post("/", response_model=TenantGroupOut, status_code=status.HTTP_201_CREATED)
def create_group(
    payload: TenantGroupCreateRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> TenantGroupOut:
    ensure_tenant_permission(
        db,
        tenant_id,
        account_id,
        TenantPermissions.SETTINGS_WRITE,
        detail=_NO_PERMISSION_TO_MANAGE_GROUPS_DETAIL,
    )
    group = tenant_group_service.create_group(
        db, tenant_id=tenant_id, name=payload.name, external_id=payload.external_id
    )
    response = TenantGroupOut.model_validate(group)
    _commit_group_audit(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        action="group.create",
        group_id=group.id,
        details={
            "name": group.name[:255],
            "has_external_id": bool(group.external_id),
        },
    )
    return response


@router.get("/{group_id}", response_model=TenantGroupOut)
def get_group(
    group_id: UUID,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> TenantGroupOut:
    ensure_tenant_permission(
        db,
        tenant_id,
        account_id,
        TenantPermissions.SETTINGS_READ,
        detail="No permission to view groups",
    )
    group = tenant_group_service.get_group(db, tenant_id=tenant_id, group_id=group_id)
    return TenantGroupOut.model_validate(group)


@router.patch("/{group_id}", response_model=TenantGroupOut)
def patch_group(
    group_id: UUID,
    payload: TenantGroupUpdateRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> TenantGroupOut:
    ensure_tenant_permission(
        db,
        tenant_id,
        account_id,
        TenantPermissions.SETTINGS_WRITE,
        detail=_NO_PERMISSION_TO_MANAGE_GROUPS_DETAIL,
    )
    group = tenant_group_service.update_group(
        db,
        tenant_id=tenant_id,
        group_id=group_id,
        name=payload.name,
        external_id=payload.external_id,
    )
    response = TenantGroupOut.model_validate(group)
    _commit_group_audit(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        action="group.update",
        group_id=group_id,
        details={
            "name": group.name[:255],
            "has_external_id": bool(group.external_id),
        },
    )
    return response


@router.delete("/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_group(
    group_id: UUID,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    ensure_tenant_permission(
        db,
        tenant_id,
        account_id,
        TenantPermissions.SETTINGS_WRITE,
        detail=_NO_PERMISSION_TO_MANAGE_GROUPS_DETAIL,
    )
    tenant_group_service.delete_group(db, tenant_id=tenant_id, group_id=group_id)
    _commit_group_audit(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        action="group.delete",
        group_id=group_id,
        details={},
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{group_id}/members", response_model=TenantGroupMemberListResponse)
def list_group_members(
    group_id: UUID,
    query: Annotated[TenantGroupMemberListQuery, Query()],
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> TenantGroupMemberListResponse:
    ensure_tenant_permission(
        db,
        tenant_id,
        account_id,
        TenantPermissions.SETTINGS_READ,
        detail="No permission to view group members",
    )
    total, members = tenant_group_service.list_members(
        db, tenant_id=tenant_id, group_id=group_id, skip=query.skip, limit=query.limit
    )
    return TenantGroupMemberListResponse(
        total=total, items=[TenantGroupMemberOut.model_validate(member) for member in members]
    )


@router.post("/{group_id}/members", response_model=TenantGroupMembersUpdateResponse)
def add_group_members(
    group_id: UUID,
    payload: TenantGroupMembersUpdateRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> TenantGroupMembersUpdateResponse:
    ensure_tenant_permission(
        db,
        tenant_id,
        account_id,
        TenantPermissions.SETTINGS_WRITE,
        detail="No permission to manage group members",
    )
    added = tenant_group_service.add_members(db, tenant_id=tenant_id, group_id=group_id, member_ids=payload.member_ids)
    _commit_group_audit(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        action="group.members.add",
        group_id=group_id,
        details={
            "member_count_requested": len(payload.member_ids),
            "member_count_updated": added,
        },
    )
    return TenantGroupMembersUpdateResponse(updated=added)


@router.post(
    "/{group_id}/members/remove",
    response_model=TenantGroupMembersUpdateResponse,
)
def remove_group_members(
    group_id: UUID,
    payload: TenantGroupMembersUpdateRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> TenantGroupMembersUpdateResponse:
    ensure_tenant_permission(
        db,
        tenant_id,
        account_id,
        TenantPermissions.SETTINGS_WRITE,
        detail="No permission to manage group members",
    )
    removed = tenant_group_service.remove_members(
        db, tenant_id=tenant_id, group_id=group_id, member_ids=payload.member_ids
    )
    _commit_group_audit(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        action="group.members.remove",
        group_id=group_id,
        details={
            "member_count_requested": len(payload.member_ids),
            "member_count_updated": removed,
        },
    )
    return TenantGroupMembersUpdateResponse(updated=removed)

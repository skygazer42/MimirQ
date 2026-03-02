"""
RBAC admin API (tenant-scoped).

Wave22-T092: RBAC roles (admin/editor/viewer) for datasets/connectors.

Notes:
- MimirQ currently models roles on `tenant_members.role` (tenant-scoped).
- Dataset/connector write APIs already gate on EDIT_ROLES derived from this field.
- This router provides a small admin surface to view/update member roles.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.api.schemas.rbac import TenantMemberListResponse, TenantMemberOut, TenantMemberUpdateRequest
from app.core.database import get_db
from app.models.tenant import TenantMember
from app.services.rbac_service import TenantPermissions, ensure_tenant_permission

router = APIRouter()


@router.get("/members", response_model=TenantMemberListResponse)
async def list_tenant_members(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=200, ge=1, le=1000),
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
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


@router.patch("/members/{user_id}", response_model=TenantMemberOut)
async def patch_tenant_member_role(
    user_id: str,
    payload: TenantMemberUpdateRequest,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
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

    member = (
        db.query(TenantMember)
        .filter(TenantMember.tenant_id == tenant_id, TenantMember.user_id == uid)
        .first()
    )
    if not member:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant member not found")

    member.role = str(payload.role or "").strip().lower()
    db.commit()
    db.refresh(member)
    return TenantMemberOut.model_validate(member)


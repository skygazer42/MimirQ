"""
Audit log endpoints (admin-only).

This is intentionally minimal and PII-safe by default.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.core.database import get_db
from app.models.audit_log import AuditLog
from app.services.dataset_service import DatasetService

router = APIRouter()

_ADMIN_ROLES = {"owner", "admin"}


def _ensure_admin(db: Session, tenant_id: UUID, account_id: str) -> None:
    member = DatasetService.ensure_member(db, tenant_id, account_id)
    role = (member.role or "").lower()
    if role not in _ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="No permission to access audit logs")


class AuditLogOut(BaseModel):
    id: UUID
    tenant_id: UUID
    actor_id: Optional[str] = None
    action: str
    resource_type: Optional[str] = None
    resource_id: Optional[str] = None
    request_id: Optional[str] = None
    ip: Optional[str] = None
    user_agent: Optional[str] = None
    details: Dict[str, Any] = {}
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AuditLogListResponse(BaseModel):
    total: int
    items: List[AuditLogOut]


@router.get("/logs", response_model=AuditLogListResponse)
def list_audit_logs(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    actor_id: Optional[str] = Query(default=None, max_length=255),
    action: Optional[str] = Query(default=None, max_length=128),
    resource_type: Optional[str] = Query(default=None, max_length=64),
    resource_id: Optional[str] = Query(default=None, max_length=255),
    request_id: Optional[str] = Query(default=None, max_length=128),
    since: Optional[datetime] = Query(default=None),
    until: Optional[datetime] = Query(default=None),
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    _ensure_admin(db, tenant_id, account_id)

    q = db.query(AuditLog).filter(AuditLog.tenant_id == tenant_id)

    if actor_id:
        q = q.filter(AuditLog.actor_id == actor_id)
    if action:
        q = q.filter(AuditLog.action == action)
    if resource_type:
        q = q.filter(AuditLog.resource_type == resource_type)
    if resource_id:
        q = q.filter(AuditLog.resource_id == resource_id)
    if request_id:
        q = q.filter(AuditLog.request_id == request_id)
    if since is not None:
        q = q.filter(AuditLog.created_at >= since)
    if until is not None:
        q = q.filter(AuditLog.created_at <= until)

    total = int(q.count())
    items = (
        q.order_by(desc(AuditLog.created_at), desc(AuditLog.id))
        .offset(skip)
        .limit(limit)
        .all()
    )
    return {"total": total, "items": items}


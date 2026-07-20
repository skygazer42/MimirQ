
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.core.database import get_db
from app.services.rbac_service import TenantPermissions, ensure_tenant_permission
from app.services.rtbf_cascade import run_rtbf_cascade

_DEFAULT_HTTP_EXCEPTION_RESPONSES = {
    400: {"description": "Bad Request"},
    403: {"description": "Forbidden"},
    404: {"description": "Not Found"},
    409: {"description": "Conflict"},
    416: {"description": "Range Not Satisfiable"},
}

router = APIRouter(responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)


class RTBFRequest(BaseModel):
    subject_account_id: str = Field(min_length=1, max_length=255)
    dry_run: bool = True
    max_docs: int = Field(default=100, ge=1, le=1000)
    max_retries: int = Field(default=1, ge=0, le=10)


class RTBFStatusResponse(BaseModel):
    ticket_id: str
    status: str = "accepted"
    note: str = "RTBF status persistence is not enabled in this scaffold"


@router.post("/request", responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def request_rtbf_cascade(
    body: RTBFRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    ensure_tenant_permission(
        db,
        tenant_id,
        account_id,
        TenantPermissions.LIFECYCLE_MANAGE,
        detail="No permission to execute RTBF deletion",
    )
    return await run_rtbf_cascade(
        db,
        tenant_id=tenant_id,
        subject_account_id=str(body.subject_account_id or "").strip(),
        dry_run=bool(body.dry_run),
        actor_id=str(account_id or "").strip() or "system:rtbf",
        max_docs=int(body.max_docs or 0),
        max_retries=int(body.max_retries or 0),
    )


@router.get("/status/{ticket_id}", responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def get_rtbf_status(
    ticket_id: str,
    *,
    _tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    _account_id: Annotated[str, Depends(get_current_account_id)],
) -> RTBFStatusResponse:
    return RTBFStatusResponse(ticket_id=str(ticket_id or "").strip())

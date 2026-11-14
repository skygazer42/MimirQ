from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_account_id, get_tenant_id
from app.api.utils import DEFAULT_HTTP_EXCEPTION_RESPONSES as _DEFAULT_HTTP_EXCEPTION_RESPONSES
from app.core.async_bridge import run_blocking_in_thread
from app.core.database import SessionLocal, get_db
from app.services.rbac_service import TenantPermissions, ensure_tenant_permission
from app.services.rtbf_cascade import run_rtbf_cascade

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


def _authorize_rtbf_request(tenant_id: UUID, account_id: str) -> None:
    with SessionLocal() as db:
        ensure_tenant_permission(
            db,
            tenant_id,
            account_id,
            TenantPermissions.LIFECYCLE_MANAGE,
            detail="No permission to execute RTBF deletion",
        )


@router.post("/request")
async def request_rtbf_cascade(
    body: RTBFRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    await run_blocking_in_thread(_authorize_rtbf_request, tenant_id, account_id)
    return await run_rtbf_cascade(
        db,
        tenant_id=tenant_id,
        subject_account_id=body.subject_account_id.strip(),
        dry_run=body.dry_run,
        actor_id=account_id,
        max_docs=body.max_docs,
        max_retries=body.max_retries,
    )


@router.get("/status/{ticket_id}")
async def get_rtbf_status(
    ticket_id: str,
    *,
    _tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    _account_id: Annotated[str, Depends(get_current_account_id)],
) -> RTBFStatusResponse:
    return RTBFStatusResponse(ticket_id=ticket_id.strip())

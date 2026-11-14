from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from app.api.dependencies import get_current_account_id, get_tenant_id
from app.api.schemas.documents import BatchTaskStatus, BatchUploadRequest, BatchUploadResponse
from app.core.async_bridge import run_blocking_in_thread
from app.core.database import SessionLocal
from app.services import dataset_service
from app.services.dataset_service import EDIT_ROLES
from app.services.mineru_service import mineru_service

router = APIRouter(
    responses={
        400: {"description": "Bad Request"},
        403: {"description": "Forbidden"},
        404: {"description": "Not Found"},
        500: {"description": "Internal Server Error"},
    }
)


def _require_batch_member(*, tenant_id: UUID, account_id: str) -> str:
    """Authorize membership in the worker and return the detached role value."""
    with SessionLocal() as db:
        return dataset_service.ensure_member(db, tenant_id, account_id).role


@router.post("/batch-upload/apply-urls", response_model=BatchUploadResponse)
async def apply_batch_upload_urls(
    request: BatchUploadRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
) -> BatchUploadResponse:
    """
    Batch request file upload URLs (MinerU online parsing).

    Use case: batch upload local files for parsing.
    """
    role = await run_blocking_in_thread(_require_batch_member, tenant_id=tenant_id, account_id=account_id)
    if role.lower() not in EDIT_ROLES:
        raise HTTPException(status_code=403, detail="No permission to apply upload URLs")

    files = [file.model_dump() for file in request.files]
    try:
        result = await mineru_service.aapply_batch_upload_urls(files=files)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=f"Failed to apply upload URLs: {exc}") from exc
    return BatchUploadResponse(batch_id=result["batch_id"], file_urls=result["file_urls"], files=request.files)


@router.get("/batch-upload/status/{batch_id}", response_model=BatchTaskStatus)
async def get_batch_task_status(
    batch_id: str,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
) -> BatchTaskStatus:
    """
    Query batch parsing task status.
    """
    await run_blocking_in_thread(_require_batch_member, tenant_id=tenant_id, account_id=account_id)
    try:
        status = await mineru_service.aget_task_status(batch_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=f"Failed to get task status: {exc}") from exc
    return BatchTaskStatus(batch_id=batch_id, **status)

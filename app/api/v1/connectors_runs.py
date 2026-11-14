from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_account_id, get_tenant_id
from app.api.schemas.sources import (
    ConnectorRunCreateRequest,
    ConnectorRunListQuery,
    ConnectorRunListResponse,
    ConnectorRunOut,
)
from app.api.utils import DEFAULT_HTTP_EXCEPTION_RESPONSES
from app.core.database import get_db
from app.services import connector_run_operations

router = APIRouter(responses=DEFAULT_HTTP_EXCEPTION_RESPONSES)


@router.post("/runs", response_model=ConnectorRunOut, status_code=201)
async def create_connector_run(
    payload: ConnectorRunCreateRequest,
    background_tasks: BackgroundTasks,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> ConnectorRunOut:
    return await connector_run_operations.create_run(
        payload=payload,
        background_tasks=background_tasks,
        db=db,
        tenant_id=tenant_id,
        account_id=account_id,
    )


@router.get("/runs", response_model=ConnectorRunListResponse)
def list_connector_runs(
    params: Annotated[ConnectorRunListQuery, Query()],
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, object]:
    return connector_run_operations.list_runs(
        skip=params.skip,
        limit=params.limit,
        dataset_id=params.dataset_id,
        tenant_id=tenant_id,
        account_id=account_id,
        db=db,
    )


@router.get("/runs/{run_id}", response_model=ConnectorRunOut)
def get_connector_run(
    run_id: UUID,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> ConnectorRunOut:
    return connector_run_operations.get_run(
        run_id,
        tenant_id=tenant_id,
        account_id=account_id,
        db=db,
    )


@router.post("/runs/{run_id}/retry-failed", response_model=ConnectorRunOut, status_code=201)
async def retry_failed_connector_run(
    run_id: UUID,
    background_tasks: BackgroundTasks,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> ConnectorRunOut:
    return await connector_run_operations.retry_failed_run(
        run_id,
        background_tasks,
        tenant_id=tenant_id,
        account_id=account_id,
        db=db,
    )


@router.post("/runs/{run_id}/resume", response_model=ConnectorRunOut, status_code=201)
async def resume_connector_run(
    run_id: UUID,
    background_tasks: BackgroundTasks,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> ConnectorRunOut:
    return await connector_run_operations.resume_run(
        run_id,
        background_tasks,
        tenant_id=tenant_id,
        account_id=account_id,
        db=db,
    )


@router.post("/runs/{run_id}/cancel", response_model=ConnectorRunOut)
async def cancel_connector_run(
    run_id: UUID,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> ConnectorRunOut:
    return await connector_run_operations.cancel_run(
        run_id,
        tenant_id=tenant_id,
        account_id=account_id,
        db=db,
    )

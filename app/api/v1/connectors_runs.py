from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.api.schemas.connector import ConnectorRunCreateRequest, ConnectorRunListResponse, ConnectorRunOut
from app.api.v1.connectors_common import _DEFAULT_HTTP_EXCEPTION_RESPONSES
from app.core.database import get_db
from app.services import connector_run_operations

router = APIRouter(responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)

CONNECTOR_RUN_NOT_FOUND_DETAIL = connector_run_operations.CONNECTOR_RUN_NOT_FOUND_DETAIL
CONNECTOR_QUEUE_UNAVAILABLE_DETAIL = connector_run_operations.CONNECTOR_QUEUE_UNAVAILABLE_DETAIL
CONNECTOR_QUEUE_HANDOFF_FAILED_ERROR = connector_run_operations.CONNECTOR_QUEUE_HANDOFF_FAILED_ERROR

_enqueue_or_schedule_connector_run = connector_run_operations.enqueue_or_schedule_run
_build_retry_failed_run_config = connector_run_operations._build_retry_failed_run_config
_connector_run_has_abortable_task = connector_run_operations._connector_run_has_abortable_task
_get_queue_or_none = connector_run_operations._get_queue_or_none
_load_arq_job_class = connector_run_operations._load_arq_job_class


class ConnectorRunListParams:
    def __init__(
        self,
        skip: Annotated[int, Query(ge=0)] = 0,
        limit: Annotated[int, Query(ge=1, le=200)] = 20,
        dataset_id: UUID | None = None,
    ) -> None:
        self.skip = skip
        self.limit = limit
        self.dataset_id = dataset_id


@router.post(
    "/runs",
    response_model=ConnectorRunOut,
    status_code=201,
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
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


@router.get(
    "/runs",
    response_model=ConnectorRunListResponse,
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
def list_connector_runs(
    params: Annotated[ConnectorRunListParams, Depends()],
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


@router.get(
    "/runs/{run_id}",
    response_model=ConnectorRunOut,
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
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


@router.post(
    "/runs/{run_id}/retry-failed",
    response_model=ConnectorRunOut,
    status_code=201,
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
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


@router.post(
    "/runs/{run_id}/resume",
    response_model=ConnectorRunOut,
    status_code=201,
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
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


@router.post(
    "/runs/{run_id}/cancel",
    response_model=ConnectorRunOut,
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
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

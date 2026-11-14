from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Response
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_account_id, get_tenant_id
from app.api.schemas.sources import (
    ConnectorConfigCreateRequest,
    ConnectorConfigListResponse,
    ConnectorConfigOut,
    ConnectorConfigUpdateRequest,
    ConnectorRunOut,
)
from app.api.utils import DEFAULT_HTTP_EXCEPTION_RESPONSES
from app.core.database import get_db
from app.services.connector_config_operations import (
    create_config,
    delete_config,
    list_configs,
    reconcile_config,
    run_saved_config,
    update_config,
)

router = APIRouter(responses=DEFAULT_HTTP_EXCEPTION_RESPONSES)


@router.get("/configs", response_model=ConnectorConfigListResponse)
def list_connector_configs(
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 20,
    dataset_id: UUID | None = None,
    connector_id: str | None = None,
    enabled: bool | None = None,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, object]:
    return list_configs(
        skip=skip,
        limit=limit,
        dataset_id=dataset_id,
        connector_id=connector_id,
        enabled=enabled,
        tenant_id=tenant_id,
        account_id=account_id,
        db=db,
    )


@router.post("/configs", response_model=ConnectorConfigOut, status_code=201)
def create_connector_config(
    payload: ConnectorConfigCreateRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> ConnectorConfigOut:
    return create_config(payload, tenant_id=tenant_id, account_id=account_id, db=db)


@router.put("/configs/{config_id}", response_model=ConnectorConfigOut)
def update_connector_config(
    config_id: UUID,
    payload: ConnectorConfigUpdateRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> ConnectorConfigOut:
    return update_config(config_id, payload, tenant_id=tenant_id, account_id=account_id, db=db)


@router.delete("/configs/{config_id}", status_code=204)
def delete_connector_config(
    config_id: UUID,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    delete_config(config_id, tenant_id=tenant_id, account_id=account_id, db=db)
    return Response(status_code=204)


@router.post("/configs/{config_id}/run", response_model=ConnectorRunOut, status_code=201)
async def run_connector_config(
    config_id: UUID,
    background_tasks: BackgroundTasks,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> ConnectorRunOut:
    return await run_saved_config(
        config_id,
        background_tasks,
        tenant_id=tenant_id,
        account_id=account_id,
        db=db,
    )


@router.post("/configs/{config_id}/reconcile")
def reconcile_connector_config(
    config_id: UUID,
    apply: Annotated[bool, Query(description="Apply the reconcile plan; default is dry-run")] = False,
    sample_limit: Annotated[int, Query(ge=1, le=200)] = 20,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, object]:
    return reconcile_config(
        config_id,
        apply=apply,
        sample_limit=sample_limit,
        tenant_id=tenant_id,
        account_id=account_id,
        db=db,
    )

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.api.v1.connectors_common import _DEFAULT_HTTP_EXCEPTION_RESPONSES
from app.core.database import get_db
from app.services.connector_schedule_operations import tick_schedules

router = APIRouter(responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)


@router.post("/scheduled/tick", responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def scheduled_tick(
    background_tasks: BackgroundTasks,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, int]:
    """Evaluate saved connector schedules and enqueue due runs."""
    return await tick_schedules(
        background_tasks=background_tasks,
        db=db,
        tenant_id=tenant_id,
        account_id=account_id,
    )

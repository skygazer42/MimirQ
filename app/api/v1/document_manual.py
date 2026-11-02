from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.api.schemas.document import DocumentDetail, ManualDocumentCreate
from app.core.database import get_db
from app.models.document import Document as DBDocument
from app.services.document_manual_ingestion import create_manual_document

_DEFAULT_HTTP_EXCEPTION_RESPONSES = {
    400: {"description": "Bad Request"},
    403: {"description": "Forbidden"},
    404: {"description": "Not Found"},
    409: {"description": "Conflict"},
    416: {"description": "Range Not Satisfiable"},
}

router = APIRouter(responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)


@router.post("/manual", response_model=DocumentDetail, status_code=201, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def create_document_with_manual_chunks(
    request: ManualDocumentCreate,
    background_tasks: BackgroundTasks,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> DBDocument:
    return create_manual_document(
        request=request,
        background_tasks=background_tasks,
        db=db,
        tenant_id=tenant_id,
        account_id=account_id,
    )

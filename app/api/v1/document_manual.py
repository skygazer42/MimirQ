from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_account_id, get_tenant_id
from app.api.schemas.documents import DocumentDetail, ManualDocumentCreate
from app.api.utils import DEFAULT_HTTP_EXCEPTION_RESPONSES
from app.core.database import get_db
from app.models.document import Document
from app.services.document_manual_ingestion import create_manual_document

router = APIRouter(responses=DEFAULT_HTTP_EXCEPTION_RESPONSES)


@router.post("/manual", response_model=DocumentDetail, status_code=201)
def create_document_with_manual_chunks(
    request: ManualDocumentCreate,
    background_tasks: BackgroundTasks,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> Document:
    return create_manual_document(
        request=request,
        background_tasks=background_tasks,
        db=db,
        tenant_id=tenant_id,
        account_id=account_id,
    )

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_account_id, get_tenant_id
from app.api.schemas.documents import DocumentAccessInfo, DocumentAccessUpdateRequest
from app.api.utils import DEFAULT_HTTP_EXCEPTION_RESPONSES
from app.core.database import get_db
from app.services import document_access_service

router = APIRouter(responses=DEFAULT_HTTP_EXCEPTION_RESPONSES)


@router.get("/{document_id}/access", response_model=DocumentAccessInfo)
def get_document_access(
    document_id: UUID,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> DocumentAccessInfo:
    return document_access_service.get_document_access(
        document_id=document_id,
        tenant_id=tenant_id,
        account_id=account_id,
        db=db,
    )


@router.put("/{document_id}/access", response_model=DocumentAccessInfo)
def put_document_access(
    document_id: UUID,
    payload: DocumentAccessUpdateRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> DocumentAccessInfo:
    return document_access_service.update_document_access(
        document_id=document_id,
        payload=payload,
        tenant_id=tenant_id,
        account_id=account_id,
        db=db,
    )

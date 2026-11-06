from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.api.schemas.document import (
    DocumentDetail,
    DocumentPipelinePatchRequest,
    DocumentUserMetadataPatchRequest,
)
from app.api.schemas.qa import (
    DocumentQAGenerateRequest,
    DocumentQAGenerateResponse,
)
from app.core.database import get_db
from app.models.document import Document as DBDocument
from app.services import document_metadata_operations, document_qa_service

_DEFAULT_HTTP_EXCEPTION_RESPONSES = {
    400: {"description": "Bad Request"},
    403: {"description": "Forbidden"},
    404: {"description": "Not Found"},
    409: {"description": "Conflict"},
    416: {"description": "Range Not Satisfiable"},
}

router = APIRouter(responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)


@router.post(
    "/{document_id}/qa/generate",
    response_model=DocumentQAGenerateResponse,
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
def generate_document_qa(
    document_id: UUID,
    payload: DocumentQAGenerateRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> DocumentQAGenerateResponse:
    return document_qa_service.generate_document_qa(
        document_id=document_id,
        payload=payload,
        db=db,
        tenant_id=tenant_id,
        account_id=account_id,
    )


@router.patch(
    "/{document_id}/pipeline",
    response_model=DocumentDetail,
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
def patch_document_pipeline(
    document_id: UUID,
    payload: DocumentPipelinePatchRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> DBDocument:
    return document_metadata_operations.patch_pipeline(
        document_id=document_id,
        payload=payload,
        db=db,
        tenant_id=tenant_id,
        account_id=account_id,
    )


@router.patch(
    "/{document_id}/metadata",
    response_model=DocumentDetail,
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
def patch_document_user_metadata(
    document_id: UUID,
    payload: DocumentUserMetadataPatchRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> DBDocument:
    return document_metadata_operations.patch_user_metadata(
        document_id=document_id,
        payload=payload,
        db=db,
        tenant_id=tenant_id,
        account_id=account_id,
    )

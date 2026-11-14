from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_account_id, get_tenant_id
from app.api.schemas.documents import (
    DocumentDetail,
    DocumentPipelinePatchRequest,
    DocumentQAGenerateRequest,
    DocumentQAGenerateResponse,
    DocumentUserMetadataPatchRequest,
)
from app.api.utils import DEFAULT_HTTP_EXCEPTION_RESPONSES
from app.core.database import get_db
from app.models.document import Document
from app.services import document_metadata_operations, document_qa_service

router = APIRouter(responses=DEFAULT_HTTP_EXCEPTION_RESPONSES)


@router.post("/{document_id}/qa/generate", response_model=DocumentQAGenerateResponse)
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


@router.patch("/{document_id}/pipeline", response_model=DocumentDetail)
def patch_document_pipeline(
    document_id: UUID,
    payload: DocumentPipelinePatchRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> Document:
    return document_metadata_operations.patch_pipeline(
        document_id=document_id,
        payload=payload,
        db=db,
        tenant_id=tenant_id,
        account_id=account_id,
    )


@router.patch("/{document_id}/metadata", response_model=DocumentDetail)
def patch_document_user_metadata(
    document_id: UUID,
    payload: DocumentUserMetadataPatchRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> Document:
    return document_metadata_operations.patch_user_metadata(
        document_id=document_id,
        payload=payload,
        db=db,
        tenant_id=tenant_id,
        account_id=account_id,
    )

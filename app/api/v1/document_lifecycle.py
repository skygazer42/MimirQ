from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_account_id, get_tenant_id
from app.api.schemas.documents import DocumentLifecycleMetadata, DocumentLifecycleMetadataUpdateRequest
from app.api.utils import DEFAULT_HTTP_EXCEPTION_RESPONSES
from app.core.database import get_db
from app.services import document_lifecycle_service

router = APIRouter(responses=DEFAULT_HTTP_EXCEPTION_RESPONSES)


@router.get("/{document_id}/lifecycle-metadata", response_model=DocumentLifecycleMetadata)
def get_document_lifecycle_metadata(
    document_id: UUID,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> DocumentLifecycleMetadata:
    return document_lifecycle_service.get_document_lifecycle_metadata(
        document_id=document_id,
        tenant_id=tenant_id,
        account_id=account_id,
        db=db,
    )


@router.patch("/{document_id}/lifecycle-metadata", response_model=DocumentLifecycleMetadata)
def patch_document_lifecycle_metadata(
    document_id: UUID,
    payload: DocumentLifecycleMetadataUpdateRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> DocumentLifecycleMetadata:
    return document_lifecycle_service.patch_document_lifecycle_metadata(
        document_id=document_id,
        payload=payload,
        tenant_id=tenant_id,
        account_id=account_id,
        db=db,
    )

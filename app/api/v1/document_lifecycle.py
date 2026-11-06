from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.api.schemas.document import DocumentLifecycleMetadata, DocumentLifecycleMetadataUpdateRequest
from app.core.database import get_db
from app.services.document_lifecycle_service import (
    get_document_lifecycle_metadata as get_lifecycle_metadata,
)
from app.services.document_lifecycle_service import (
    patch_document_lifecycle_metadata as patch_lifecycle_metadata,
)

_DEFAULT_HTTP_EXCEPTION_RESPONSES = {
    400: {"description": "Bad Request"},
    403: {"description": "Forbidden"},
    404: {"description": "Not Found"},
    409: {"description": "Conflict"},
    416: {"description": "Range Not Satisfiable"},
}

router = APIRouter(responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)


@router.get(
    "/{document_id}/lifecycle-metadata",
    response_model=DocumentLifecycleMetadata,
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
def get_document_lifecycle_metadata(
    document_id: UUID,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> DocumentLifecycleMetadata:
    return get_lifecycle_metadata(
        document_id=document_id,
        tenant_id=tenant_id,
        account_id=account_id,
        db=db,
    )


@router.patch(
    "/{document_id}/lifecycle-metadata",
    response_model=DocumentLifecycleMetadata,
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
def patch_document_lifecycle_metadata(
    document_id: UUID,
    payload: DocumentLifecycleMetadataUpdateRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> DocumentLifecycleMetadata:
    return patch_lifecycle_metadata(
        document_id=document_id,
        payload=payload,
        tenant_id=tenant_id,
        account_id=account_id,
        db=db,
    )

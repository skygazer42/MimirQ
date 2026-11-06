"""Typed API entries for file, URL, and batch document ingestion."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, File, UploadFile
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.api.schemas.document import DocumentBatchUploadResponse, DocumentDetail, UrlUploadRequest
from app.api.schemas.document_ingestion import (
    PipelineOverridesFormFields as PipelineOverridesFormFields,
)
from app.api.schemas.document_ingestion import (
    UploadDocumentFormFields as UploadDocumentFormFields,
)
from app.api.schemas.document_ingestion import (
    UploadDocumentsBatchFormFields as UploadDocumentsBatchFormFields,
)
from app.core.database import get_db
from app.models.document import Document as DBDocument
from app.services import document_batch_ingestion, document_ingestion
from app.services.document_ingestion import INGEST_LOCK_UNAVAILABLE_DETAIL as INGEST_LOCK_UNAVAILABLE_DETAIL
from app.storage.object.minio import minio_service as minio_service

_DEFAULT_HTTP_EXCEPTION_RESPONSES = {
    400: {"description": "Bad Request"},
    403: {"description": "Forbidden"},
    404: {"description": "Not Found"},
    409: {"description": "Conflict"},
    416: {"description": "Range Not Satisfiable"},
    503: {"description": "Service Unavailable"},
}


router = APIRouter(responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)


@router.post("/upload", response_model=DocumentDetail, status_code=201, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def upload_document(
    background_tasks: BackgroundTasks,
    file: Annotated[UploadFile, File(...)],
    form: Annotated[UploadDocumentFormFields, Depends()],
    overrides_form: Annotated[PipelineOverridesFormFields, Depends()],
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> DBDocument:
    return await document_ingestion.ingest_file(
        background_tasks=background_tasks,
        file=file,
        form=form,
        overrides_form=overrides_form,
        tenant_id=tenant_id,
        account_id=account_id,
        db=db,
    )


@router.post("/upload-url", response_model=DocumentDetail, status_code=201, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def upload_document_from_url(
    background_tasks: BackgroundTasks,
    body: UrlUploadRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> DBDocument:
    """
    Fetch a remote URL and ingest it as a document.

    Notes:
    - Disabled by default: set URL_INGEST_ENABLED=true to enable.
    - SSRF guard: blocks private/loopback/link-local hosts by default.
    """
    return await document_ingestion.ingest_url(
        background_tasks=background_tasks,
        body=body,
        tenant_id=tenant_id,
        account_id=account_id,
        db=db,
        ingestion_kind="upload_url",
    )


@router.post(
    "/upload-batch",
    response_model=DocumentBatchUploadResponse,
    status_code=201,
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
async def upload_documents_batch(
    background_tasks: BackgroundTasks,
    files: Annotated[list[UploadFile], File(...)],
    form: Annotated[UploadDocumentsBatchFormFields, Depends()],
    overrides_form: Annotated[PipelineOverridesFormFields, Depends()],
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> DocumentBatchUploadResponse:
    return await document_batch_ingestion.ingest_batch(
        background_tasks=background_tasks,
        files=files,
        form=form,
        overrides_form=overrides_form,
        tenant_id=tenant_id,
        account_id=account_id,
        db=db,
    )

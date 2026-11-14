"""Typed API entries for file, URL, and batch document ingestion."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Form
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_account_id, get_tenant_id
from app.api.schemas.documents import (
    DocumentBatchUploadResponse,
    DocumentDetail,
    UploadDocumentFormFields,
    UploadDocumentsBatchFormFields,
    UrlUploadRequest,
)
from app.core.database import get_db
from app.models.document import Document
from app.services import document_batch_ingestion, document_ingestion

router = APIRouter(
    responses={
        400: {"description": "Bad Request"},
        403: {"description": "Forbidden"},
        404: {"description": "Not Found"},
        409: {"description": "Conflict"},
        416: {"description": "Range Not Satisfiable"},
        503: {"description": "Service Unavailable"},
    }
)


@router.post("/upload", response_model=DocumentDetail, status_code=201)
async def upload_document(
    background_tasks: BackgroundTasks,
    form: Annotated[UploadDocumentFormFields, Form(media_type="multipart/form-data")],
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> Document:
    return await document_ingestion.ingest_file(
        background_tasks=background_tasks,
        file=form.file,
        form=form,
        overrides_form=form.to_pipeline_overrides(),
        tenant_id=tenant_id,
        account_id=account_id,
        db=db,
    )


@router.post("/upload-url", response_model=DocumentDetail, status_code=201)
async def upload_document_from_url(
    background_tasks: BackgroundTasks,
    body: UrlUploadRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> Document:
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


@router.post("/upload-batch", response_model=DocumentBatchUploadResponse, status_code=201)
async def upload_documents_batch(
    background_tasks: BackgroundTasks,
    form: Annotated[UploadDocumentsBatchFormFields, Form(media_type="multipart/form-data")],
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> DocumentBatchUploadResponse:
    return await document_batch_ingestion.ingest_batch(
        background_tasks=background_tasks,
        files=form.files,
        form=form,
        overrides_form=form.to_pipeline_overrides(),
        tenant_id=tenant_id,
        account_id=account_id,
        db=db,
    )

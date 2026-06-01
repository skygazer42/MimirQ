from __future__ import annotations

import uuid
from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.api.schemas.document import DocumentParsedContentResponse
from app.api.utils.response_headers import file_response_headers
from app.core.database import get_db
from app.models.dataset import Dataset
from app.models.document import Document as DBDocument
from app.models.document import DocumentParsedContent
from app.parsing.output import markdown_to_blocks, render_clean_docx_bytes
from app.services.dataset_service import DatasetService
from app.services.document_access_service import assert_document_acl_readable

_DEFAULT_HTTP_EXCEPTION_RESPONSES = {
    400: {"description": "Bad Request"},
    403: {"description": "Forbidden"},
    404: {"description": "Not Found"},
    409: {"description": "Conflict"},
    416: {"description": "Range Not Satisfiable"},
}

DOC_NOT_FOUND_DETAIL = "Document not found"

router = APIRouter(responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)


@router.get("/{document_id}/parsed-content", response_model=DocumentParsedContentResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def get_document_parsed_content(
    document_id: uuid.UUID,
    max_chars: Annotated[int, Query(ge=0, le=2000000)] = 200_000,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Get persisted parsed markdown content (raw+clean) for a document.

    Availability:
    - Only present when the ingestion pipeline enables `persist_parsed_content`.
    - When unavailable, returns `available=false` with empty strings.
    """
    DatasetService.ensure_member(db, tenant_id, account_id)

    document = (
        db.query(DBDocument)
        .filter(DBDocument.id == document_id, DBDocument.tenant_id == tenant_id)
        .first()
    )
    if not document:
        raise HTTPException(status_code=404, detail=DOC_NOT_FOUND_DETAIL)

    dataset: Dataset | None = None
    if document.dataset_id:
        dataset = DatasetService.get_dataset(db, tenant_id, document.dataset_id)
        DatasetService.assert_dataset_readable(db, dataset, account_id)
    assert_document_acl_readable(db, tenant_id=tenant_id, account_id=account_id, document=document, dataset=dataset)

    row = (
        db.query(DocumentParsedContent)
        .filter(DocumentParsedContent.document_id == document_id, DocumentParsedContent.tenant_id == tenant_id)
        .first()
    )

    doc_meta = getattr(document, "doc_metadata", None) or {}
    persisted_meta = doc_meta.get("parsed_content_persisted") if isinstance(doc_meta, dict) else None
    if not isinstance(persisted_meta, dict):
        persisted_meta = {}

    markdown = (getattr(row, "markdown_content", "") or "") if row is not None else ""
    original = (getattr(row, "original_markdown_content", "") or "") if row is not None else ""
    markdown_truncated = False
    original_truncated = False

    max_chars_eff = int(max_chars or 0)
    if max_chars_eff > 0:
        if len(markdown) > max_chars_eff:
            markdown = markdown[:max_chars_eff]
            markdown_truncated = True
        if len(original) > max_chars_eff:
            original = original[:max_chars_eff]
            original_truncated = True

    return DocumentParsedContentResponse(
        document_id=document_id,
        available=row is not None,
        markdown_content=markdown,
        original_markdown_content=original,
        persisted_meta=persisted_meta,
        markdown_truncated=markdown_truncated,
        original_markdown_truncated=original_truncated,
        max_chars=max_chars_eff,
    )


@router.get("/{document_id}/clean-docx", responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def download_document_clean_docx(
    document_id: uuid.UUID,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    DatasetService.ensure_member(db, tenant_id, account_id)

    document = (
        db.query(DBDocument)
        .filter(DBDocument.id == document_id, DBDocument.tenant_id == tenant_id)
        .first()
    )
    if not document:
        raise HTTPException(status_code=404, detail=DOC_NOT_FOUND_DETAIL)

    dataset: Dataset | None = None
    if document.dataset_id:
        dataset = DatasetService.get_dataset(db, tenant_id, document.dataset_id)
        DatasetService.assert_dataset_readable(db, dataset, account_id)
    assert_document_acl_readable(db, tenant_id=tenant_id, account_id=account_id, document=document, dataset=dataset)

    row = (
        db.query(DocumentParsedContent)
        .filter(DocumentParsedContent.document_id == document_id, DocumentParsedContent.tenant_id == tenant_id)
        .first()
    )
    if row is None or not str(getattr(row, "markdown_content", "") or "").strip():
        raise HTTPException(status_code=404, detail="Clean DOCX not available")

    title = Path(str(getattr(document, "filename", "") or "document")).stem
    markdown = str(getattr(row, "markdown_content", "") or "")
    blocks = markdown_to_blocks(markdown)
    if blocks:
        first = blocks[0] if isinstance(blocks[0], dict) else {}
        if str(first.get("type") or "").strip().lower() == "heading" and str(first.get("text") or "").strip() == title:
            blocks = blocks[1:]
    payload = render_clean_docx_bytes(title=title, blocks=blocks)
    headers = file_response_headers(f"{title}_Clean.docx", disposition="inline", cache_control=None)
    return StreamingResponse(
        iter([payload]),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers=headers,
    )

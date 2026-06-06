from __future__ import annotations

import contextlib
import importlib
import uuid
from dataclasses import asdict
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.api.schemas.document import (
    DocumentDetail,
    DocumentPipelineOptions,
    DocumentPipelinePatchRequest,
    DocumentUserMetadataPatchRequest,
)
from app.api.schemas.qa import (
    DocumentQAGenerateRequest,
    DocumentQAGenerateResponse,
    QAPairPreview,
)
from app.core.database import get_db
from app.models.dataset import Dataset
from app.models.document import Document as DBDocument
from app.services.pipeline_config import parse_pipeline_from_metadata, upsert_pipeline_metadata

_DEFAULT_HTTP_EXCEPTION_RESPONSES = {
    400: {"description": "Bad Request"},
    403: {"description": "Forbidden"},
    404: {"description": "Not Found"},
    409: {"description": "Conflict"},
    416: {"description": "Range Not Satisfiable"},
}

router = APIRouter(responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)


def _documents_module():
    return importlib.import_module("app.api.v1.documents")


@router.post(
    "/{document_id}/qa/generate",
    response_model=DocumentQAGenerateResponse,
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
async def generate_document_qa(
    document_id: uuid.UUID,
    payload: DocumentQAGenerateRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Generate (or extract) FAQ-style Q&A pairs for a document and index them as extra chunks.

    Generated chunks are tagged with `file_type=qa` in chunk metadata.
    """
    documents_module = _documents_module()
    documents_module.DatasetService.ensure_member(db, tenant_id, account_id)

    document = (
        db.query(DBDocument)
        .filter(DBDocument.id == document_id, DBDocument.tenant_id == tenant_id)
        .first()
    )
    if not document:
        raise HTTPException(status_code=404, detail=documents_module.DOC_NOT_FOUND_DETAIL)

    dataset: Dataset | None = None
    if document.dataset_id:
        dataset = documents_module.DatasetService.get_dataset(db, tenant_id, document.dataset_id)
        documents_module.DatasetService.assert_dataset_writable(db, dataset, account_id)
    documents_module._assert_document_acl_readable(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        document=document,
        dataset=dataset,
    )

    current_status = str(document.status or "").lower()
    if current_status in {"pending", "processing"}:
        raise HTTPException(status_code=409, detail=f"Cannot generate Q&A for a {current_status} document")

    result = documents_module.generate_and_index_document_qa(
        db,
        tenant_id=tenant_id,
        document=document,
        num_pairs=int(payload.num_pairs or 0),
        replace_existing=bool(payload.replace_existing),
        prefer_llm=bool(payload.prefer_llm),
        max_source_chars=int(payload.max_source_chars or 0),
        preview_pairs=int(payload.preview_pairs or 0),
    )

    documents_module.audit_log_event(
        db,
        tenant_id=tenant_id,
        actor_id=account_id,
        action="document.qa.generate",
        resource_type="document",
        resource_id=str(document_id),
        details={"mode": result.mode, "deleted": int(result.deleted), "created": int(result.created)},
    )
    with contextlib.suppress(Exception):
        db.commit()

    return DocumentQAGenerateResponse(
        document_id=document_id,
        mode=str(result.mode or "none"),
        deleted=int(result.deleted),
        created=int(result.created),
        chunk_ids=list(result.chunk_ids or []),
        preview=[QAPairPreview(**row) for row in (result.preview or [])],
    )


@router.patch(
    "/{document_id}/pipeline",
    response_model=DocumentDetail,
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
async def patch_document_pipeline(
    document_id: uuid.UUID,
    payload: DocumentPipelinePatchRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Patch `documents.metadata.pipeline` for document-level pipeline overrides.
    """
    documents_module = _documents_module()
    documents_module.DatasetService.ensure_member(db, tenant_id, account_id)

    document = (
        db.query(DBDocument)
        .filter(DBDocument.id == document_id, DBDocument.tenant_id == tenant_id)
        .first()
    )
    if not document:
        raise HTTPException(status_code=404, detail=documents_module.DOC_NOT_FOUND_DETAIL)

    if document.dataset_id:
        dataset = documents_module.DatasetService.get_dataset(db, tenant_id, document.dataset_id)
        documents_module.DatasetService.assert_dataset_writable(db, dataset, account_id)

    current_status = str(document.status or "").lower()
    if current_status == "processing" or (
        current_status == "pending"
        and not documents_module._is_uploaded_only_pending_document(document)
    ):
        raise HTTPException(status_code=409, detail=f"Cannot edit pipeline for a {current_status} document")

    meta = dict(document.doc_metadata or {})
    current_opts = parse_pipeline_from_metadata(meta)
    base = {} if bool(payload.replace) else asdict(current_opts)

    patch = payload.patch or DocumentPipelineOptions()
    for field in getattr(patch, "model_fields_set", set()):
        base[field] = getattr(patch, field)

    next_opts = documents_module.PipelineOptions(**base)
    upsert_pipeline_metadata(meta, options=next_opts)
    meta["pipeline_hash"] = documents_module._compute_pipeline_hash(meta)

    document.doc_metadata = meta
    db.commit()
    db.refresh(document)
    try:
        fields = sorted(getattr(patch, "model_fields_set", set()))
        documents_module.audit_log_event(
            db,
            tenant_id=tenant_id,
            actor_id=account_id,
            action="document.pipeline.patch",
            resource_type="document",
            resource_id=str(document_id),
            details={"replace": bool(payload.replace), "fields": fields[:50]},
        )
        db.commit()
    except Exception:
        db.rollback()
    return document


@router.patch(
    "/{document_id}/metadata",
    response_model=DocumentDetail,
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
async def patch_document_user_metadata(
    document_id: uuid.UUID,
    payload: DocumentUserMetadataPatchRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Patch `documents.metadata.user` for user-editable document metadata.
    """
    documents_module = _documents_module()
    documents_module.DatasetService.ensure_member(db, tenant_id, account_id)

    document = (
        db.query(DBDocument)
        .filter(DBDocument.id == document_id, DBDocument.tenant_id == tenant_id)
        .first()
    )
    if not document:
        raise HTTPException(status_code=404, detail=documents_module.DOC_NOT_FOUND_DETAIL)

    if document.dataset_id:
        dataset = documents_module.DatasetService.get_dataset(db, tenant_id, document.dataset_id)
        documents_module.DatasetService.assert_dataset_writable(db, dataset, account_id)

    meta = dict(document.doc_metadata or {})
    current_user = meta.get("user") if isinstance(meta.get("user"), dict) else {}
    patch = payload.patch if isinstance(payload.patch, dict) else {}
    next_user = documents_module._apply_user_metadata_patch(current=current_user, patch=patch, replace=payload.replace)

    meta["user"] = next_user
    document.doc_metadata = meta
    db.commit()
    db.refresh(document)
    try:
        keys = sorted([str(key) for key in patch.keys()]) if isinstance(patch, dict) else []
        details: dict[str, Any] = {"replace": bool(payload.replace), "keys": keys[:50]}
        if "quarantine_action" in patch:
            value = patch.get("quarantine_action")
            if isinstance(value, str) and value.strip():
                details["quarantine_action"] = value.strip()[:200]
        if "quarantine_reviewed" in patch:
            details["quarantine_reviewed"] = bool(patch.get("quarantine_reviewed"))
        documents_module.audit_log_event(
            db,
            tenant_id=tenant_id,
            actor_id=account_id,
            action="document.metadata.user.patch",
            resource_type="document",
            resource_id=str(document_id),
            details=details,
        )
        db.commit()
    except Exception:
        db.rollback()
    return document

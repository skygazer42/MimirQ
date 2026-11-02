import contextlib
from dataclasses import asdict
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
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
    QAPairPreview,
)
from app.core.database import get_db
from app.models.document import Document as DBDocument
from app.services import dataset_service, document_access_service
from app.services.audit_log_service import audit_log_event
from app.services.document_identity import compute_pipeline_hash
from app.services.document_lifecycle_service import DOC_NOT_FOUND_DETAIL, is_reprocessable_pending_document
from app.services.document_metadata_service import apply_user_metadata_patch
from app.services.document_qa_service import generate_and_index_document_qa
from app.services.pipeline_config import PipelineOptions, parse_pipeline_from_metadata, upsert_pipeline_metadata

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
    """
    Generate (or extract) FAQ-style Q&A pairs for a document and index them as extra chunks.

    Generated chunks are tagged with `file_type=qa` in chunk metadata.
    """
    dataset_service.ensure_member(db, tenant_id, account_id)

    document = db.query(DBDocument).filter(DBDocument.id == document_id, DBDocument.tenant_id == tenant_id).first()
    if not document:
        raise HTTPException(status_code=404, detail=DOC_NOT_FOUND_DETAIL)

    document_access_service.assert_document_writable_for_lifecycle(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        document=document,
    )

    current_status = document.status.lower()
    if current_status in {"pending", "processing"}:
        raise HTTPException(status_code=409, detail=f"Cannot generate Q&A for a {current_status} document")

    result = generate_and_index_document_qa(
        db,
        tenant_id=tenant_id,
        document=document,
        num_pairs=payload.num_pairs,
        replace_existing=payload.replace_existing,
        prefer_llm=payload.prefer_llm,
        max_source_chars=payload.max_source_chars,
        preview_pairs=payload.preview_pairs,
    )

    audit_log_event(
        db,
        tenant_id=tenant_id,
        actor_id=account_id,
        action="document.qa.generate",
        resource_type="document",
        resource_id=str(document_id),
        details={"mode": result.mode, "deleted": result.deleted, "created": result.created},
    )
    with contextlib.suppress(Exception):
        db.commit()

    return DocumentQAGenerateResponse(
        document_id=document_id,
        mode=str(result.mode or "none"),
        deleted=result.deleted,
        created=result.created,
        chunk_ids=result.chunk_ids,
        preview=[QAPairPreview(**row) for row in result.preview],
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
    """
    Patch `documents.metadata.pipeline` for document-level pipeline overrides.
    """
    dataset_service.ensure_member(db, tenant_id, account_id)

    document = db.query(DBDocument).filter(DBDocument.id == document_id, DBDocument.tenant_id == tenant_id).first()
    if not document:
        raise HTTPException(status_code=404, detail=DOC_NOT_FOUND_DETAIL)

    document_access_service.assert_document_writable_for_lifecycle(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        document=document,
    )

    current_status = document.status.lower()
    if current_status == "processing" or (
        current_status == "pending" and not is_reprocessable_pending_document(document)
    ):
        raise HTTPException(status_code=409, detail=f"Cannot edit pipeline for a {current_status} document")

    meta = dict(document.doc_metadata or {})
    current_opts = parse_pipeline_from_metadata(meta)
    base = {} if payload.replace else asdict(current_opts)

    patch = payload.patch
    for field in patch.model_fields_set:
        base[field] = getattr(patch, field)

    next_opts = PipelineOptions(**base)
    upsert_pipeline_metadata(meta, options=next_opts)
    meta["pipeline_hash"] = compute_pipeline_hash(meta)

    document.doc_metadata = meta
    db.commit()
    db.refresh(document)
    try:
        fields = sorted(patch.model_fields_set)
        audit_log_event(
            db,
            tenant_id=tenant_id,
            actor_id=account_id,
            action="document.pipeline.patch",
            resource_type="document",
            resource_id=str(document_id),
            details={"replace": payload.replace, "fields": fields[:50]},
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
def patch_document_user_metadata(
    document_id: UUID,
    payload: DocumentUserMetadataPatchRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> DBDocument:
    """
    Patch `documents.metadata.user` for user-editable document metadata.
    """
    dataset_service.ensure_member(db, tenant_id, account_id)

    document = db.query(DBDocument).filter(DBDocument.id == document_id, DBDocument.tenant_id == tenant_id).first()
    if not document:
        raise HTTPException(status_code=404, detail=DOC_NOT_FOUND_DETAIL)

    document_access_service.assert_document_writable_for_lifecycle(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        document=document,
    )

    meta = dict(document.doc_metadata or {})
    current_user = meta.get("user") if isinstance(meta.get("user"), dict) else {}
    patch = payload.patch
    next_user = apply_user_metadata_patch(current=current_user, patch=patch, replace=payload.replace)

    meta["user"] = next_user
    document.doc_metadata = meta
    db.commit()
    db.refresh(document)
    try:
        keys = sorted(patch)
        details: dict[str, Any] = {"replace": payload.replace, "keys": keys[:50]}
        if "quarantine_action" in patch:
            value = patch.get("quarantine_action")
            if isinstance(value, str) and value.strip():
                details["quarantine_action"] = value.strip()[:200]
        if "quarantine_reviewed" in patch:
            details["quarantine_reviewed"] = bool(patch.get("quarantine_reviewed"))
        audit_log_event(
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

"""Authorized document metadata and QA business operations."""

from collections.abc import Mapping
from dataclasses import asdict
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.api.schemas.documents import DocumentPipelinePatchRequest, DocumentUserMetadataPatchRequest
from app.models.document import Document as DBDocument
from app.rag.core.logging import get_logger
from app.services.audit_log_service import audit_log_event
from app.services.document_access_service import assert_document_writable_for_lifecycle, get_document_for_lifecycle
from app.services.document_identity import compute_pipeline_hash
from app.services.document_lifecycle_service import DOC_NOT_FOUND_DETAIL
from app.services.document_processing_operations import is_reprocessable_pending_document
from app.services.document_user_metadata import apply_user_metadata_patch
from app.services.pipeline_config import parse_pipeline_from_metadata, upsert_pipeline_metadata
from app.types.pipeline import PipelineOptions

logger = get_logger("services.document_metadata_operations")


def _get_writable_document(*, db: Session, document_id: UUID, tenant_id: UUID, account_id: str) -> DBDocument:
    document = get_document_for_lifecycle(db, tenant_id, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail=DOC_NOT_FOUND_DETAIL)
    assert_document_writable_for_lifecycle(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        document=document,
    )
    return document


def _commit_audit_event(
    db: Session,
    *,
    tenant_id: UUID,
    account_id: str,
    action: str,
    document_id: UUID,
    details: Mapping[str, object],
) -> None:
    try:
        audit_log_event(
            db,
            tenant_id=tenant_id,
            actor_id=account_id,
            action=action,
            resource_type="document",
            resource_id=str(document_id),
            details=dict(details),
        )
        db.commit()
    except Exception:
        db.rollback()
        logger.warning(
            "Document mutation committed but audit logging failed: action=%s document_id=%s",
            action,
            document_id,
            exc_info=True,
        )


def patch_pipeline(
    *,
    document_id: UUID,
    payload: DocumentPipelinePatchRequest,
    db: Session,
    tenant_id: UUID,
    account_id: str,
) -> DBDocument:
    document = _get_writable_document(db=db, document_id=document_id, tenant_id=tenant_id, account_id=account_id)
    status = document.status.lower()
    if status == "processing" or (status == "pending" and not is_reprocessable_pending_document(document)):
        raise HTTPException(status_code=409, detail=f"Cannot edit pipeline for a {status} document")

    metadata = dict(document.doc_metadata or {})
    current_options = parse_pipeline_from_metadata(metadata)
    options = {} if payload.replace else asdict(current_options)
    patch = payload.patch
    for field in patch.model_fields_set:
        options[field] = getattr(patch, field)

    next_options = PipelineOptions(**options)
    upsert_pipeline_metadata(metadata, options=next_options)
    metadata["pipeline_hash"] = compute_pipeline_hash(metadata)
    document.doc_metadata = metadata
    db.commit()
    db.refresh(document)
    fields = sorted(patch.model_fields_set)
    _commit_audit_event(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        action="document.pipeline.patch",
        document_id=document_id,
        details={"replace": payload.replace, "fields": fields[:50]},
    )
    return document


def patch_user_metadata(
    *,
    document_id: UUID,
    payload: DocumentUserMetadataPatchRequest,
    db: Session,
    tenant_id: UUID,
    account_id: str,
) -> DBDocument:
    document = _get_writable_document(db=db, document_id=document_id, tenant_id=tenant_id, account_id=account_id)
    metadata = dict(document.doc_metadata or {})
    current = metadata.get("user") if isinstance(metadata.get("user"), dict) else {}
    patch = payload.patch
    metadata["user"] = apply_user_metadata_patch(current=current, patch=patch, replace=payload.replace)
    document.doc_metadata = metadata
    db.commit()
    db.refresh(document)

    keys = sorted(patch)
    details: dict[str, object] = {"replace": payload.replace, "keys": keys[:50]}
    if isinstance(patch.get("quarantine_action"), str) and patch["quarantine_action"].strip():
        details["quarantine_action"] = patch["quarantine_action"].strip()[:200]
    if "quarantine_reviewed" in patch:
        details["quarantine_reviewed"] = bool(patch["quarantine_reviewed"])
    _commit_audit_event(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        action="document.metadata.user.patch",
        document_id=document_id,
        details=details,
    )
    return document

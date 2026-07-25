
import uuid
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.api.schemas.document import DocumentLifecycleMetadata, DocumentLifecycleMetadataUpdateRequest
from app.core.database import get_db
from app.rag.core.hashing import stable_hash
from app.services.audit_log_service import audit_log_event
from app.services.dataset_service import DatasetService
from app.services.document_access_service import (
    assert_document_writable_for_lifecycle,
    get_document_for_lifecycle,
)

_DEFAULT_HTTP_EXCEPTION_RESPONSES = {
    400: {"description": "Bad Request"},
    403: {"description": "Forbidden"},
    404: {"description": "Not Found"},
    409: {"description": "Conflict"},
    416: {"description": "Range Not Satisfiable"},
}

DOC_NOT_FOUND_DETAIL = "Document not found"

router = APIRouter(responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)


@router.get("/{document_id}/lifecycle-metadata", response_model=DocumentLifecycleMetadata, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def get_document_lifecycle_metadata(
    document_id: uuid.UUID,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Get document lifecycle governance metadata.

    RBAC: dataset editor/admin (dataset writable) when the document belongs to a dataset.
    """
    DatasetService.ensure_member(db, tenant_id, account_id)

    document = get_document_for_lifecycle(db, tenant_id, document_id)
    if not document:
        raise HTTPException(status_code=404, detail=DOC_NOT_FOUND_DETAIL)

    assert_document_writable_for_lifecycle(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        document=document,
    )

    return DocumentLifecycleMetadata(
        lifecycle_owner=getattr(document, "lifecycle_owner", None),
        review_due_at=getattr(document, "review_due_at", None),
        authority_level=getattr(document, "authority_level", None),
        supersedes_document_id=getattr(document, "supersedes_document_id", None),
        publication_status=str(getattr(document, "publication_status", "published") or "published"),
    )


@router.patch("/{document_id}/lifecycle-metadata", response_model=DocumentLifecycleMetadata, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def patch_document_lifecycle_metadata(
    document_id: uuid.UUID,
    payload: DocumentLifecycleMetadataUpdateRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Patch document lifecycle governance metadata (owner/review_due/authority/supersedes).

    Notes:
    - This does not mutate `documents.metadata.*`; it updates first-class columns.
    - Audit log is best-effort and PII-minimal by construction.

    RBAC: dataset editor/admin (dataset writable) when the document belongs to a dataset.
    """
    DatasetService.ensure_member(db, tenant_id, account_id)

    document = get_document_for_lifecycle(db, tenant_id, document_id)
    if not document:
        raise HTTPException(status_code=404, detail=DOC_NOT_FOUND_DETAIL)

    assert_document_writable_for_lifecycle(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        document=document,
    )

    fields_set = set(getattr(payload, "model_fields_set", set()) or set())
    if not fields_set:
        return DocumentLifecycleMetadata(
            lifecycle_owner=getattr(document, "lifecycle_owner", None),
            review_due_at=getattr(document, "review_due_at", None),
            authority_level=getattr(document, "authority_level", None),
            supersedes_document_id=getattr(document, "supersedes_document_id", None),
            publication_status=str(getattr(document, "publication_status", "published") or "published"),
        )

    before = {
        "lifecycle_owner": getattr(document, "lifecycle_owner", None),
        "review_due_at": getattr(document, "review_due_at", None),
        "authority_level": getattr(document, "authority_level", None),
        "supersedes_document_id": getattr(document, "supersedes_document_id", None),
        "publication_status": getattr(document, "publication_status", None),
    }

    if "lifecycle_owner" in fields_set:
        owner = payload.lifecycle_owner
        if owner is not None:
            owner = str(owner).strip()
        if not owner:
            owner = None
        document.lifecycle_owner = owner  # type: ignore[assignment]

    if "review_due_at" in fields_set:
        document.review_due_at = payload.review_due_at  # type: ignore[assignment]

    if "authority_level" in fields_set:
        document.authority_level = payload.authority_level  # type: ignore[assignment]

    if "supersedes_document_id" in fields_set:
        supersedes_document_id = payload.supersedes_document_id
        if supersedes_document_id is not None and str(supersedes_document_id) == str(document.id):
            raise HTTPException(status_code=400, detail="supersedes_document_id cannot equal document_id")
        document.supersedes_document_id = supersedes_document_id  # type: ignore[assignment]

    if "publication_status" in fields_set:
        document.publication_status = str(payload.publication_status or "published")  # type: ignore[assignment]

    db.commit()
    db.refresh(document)

    try:
        after = {
            "lifecycle_owner": getattr(document, "lifecycle_owner", None),
            "review_due_at": getattr(document, "review_due_at", None),
            "authority_level": getattr(document, "authority_level", None),
            "supersedes_document_id": getattr(document, "supersedes_document_id", None),
            "publication_status": getattr(document, "publication_status", None),
        }
        changed_fields: list[str] = []
        for key in ("lifecycle_owner", "review_due_at", "authority_level", "supersedes_document_id", "publication_status"):
            if key in fields_set and before.get(key) != after.get(key):
                changed_fields.append(key)

        details: dict[str, Any] = {
            "fields": sorted(fields_set)[:50],
            "changed_fields": changed_fields[:50],
        }
        if "lifecycle_owner" in fields_set:
            raw = str(after.get("lifecycle_owner") or "")
            details["lifecycle_owner_hash"] = stable_hash(raw, length=16) if raw else None
        if "review_due_at" in fields_set:
            due = after.get("review_due_at")
            details["review_due_at"] = due.isoformat() if due is not None else None
        if "authority_level" in fields_set:
            details["authority_level"] = after.get("authority_level")
        if "supersedes_document_id" in fields_set:
            supersedes_document_id = after.get("supersedes_document_id")
            details["supersedes_document_id"] = str(supersedes_document_id) if supersedes_document_id is not None else None
        if "publication_status" in fields_set:
            details["publication_status"] = after.get("publication_status")

        audit_log_event(
            db,
            tenant_id=tenant_id,
            actor_id=account_id,
            action="document.lifecycle_metadata.patch",
            resource_type="document",
            resource_id=str(document_id),
            details=details,
        )
        db.commit()
    except Exception:
        db.rollback()

    return DocumentLifecycleMetadata(
        lifecycle_owner=getattr(document, "lifecycle_owner", None),
        review_due_at=getattr(document, "review_due_at", None),
        authority_level=getattr(document, "authority_level", None),
        supersedes_document_id=getattr(document, "supersedes_document_id", None),
        publication_status=str(getattr(document, "publication_status", "published") or "published"),
    )

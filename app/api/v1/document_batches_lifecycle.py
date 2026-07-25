
import importlib
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.api.schemas.document import (
    DocumentBatchDeleteRequest,
    DocumentBatchDeleteResponse,
    DocumentBatchLifecycleRequest,
    DocumentBatchLifecycleResponse,
)
from app.core.database import get_db

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


@router.post("/batch/disable", response_model=DocumentBatchLifecycleResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def batch_disable_documents(
    payload: DocumentBatchLifecycleRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """Batch disable documents (best-effort)."""
    documents_module = _documents_module()
    documents_module.DatasetService.ensure_member(db, tenant_id, account_id)

    updated = 0
    not_found: list[UUID] = []
    denied: list[UUID] = []
    conflicts: list[UUID] = []

    now = datetime.now(UTC)

    for document_id in payload.document_ids:
        doc = documents_module._get_document_for_lifecycle(db, tenant_id, document_id)
        if not doc:
            not_found.append(document_id)
            continue
        try:
            documents_module._assert_document_writable_for_lifecycle(
                db,
                tenant_id=tenant_id,
                account_id=account_id,
                document=doc,
            )
        except HTTPException:
            denied.append(document_id)
            continue

        if getattr(doc, "disabled_at", None) is None:
            doc.disabled_at = now
            updated += 1

            documents_module.audit_log_event(
                db,
                tenant_id=tenant_id,
                actor_id=account_id,
                action="document.disable",
                resource_type="document",
                resource_id=str(document_id),
                details={"disabled_at": now.isoformat()},
            )

    if updated:
        db.commit()

    return {"updated": updated, "not_found": not_found, "denied": denied, "conflicts": conflicts}


@router.post("/batch/enable", response_model=DocumentBatchLifecycleResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def batch_enable_documents(
    payload: DocumentBatchLifecycleRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """Batch enable documents (best-effort)."""
    documents_module = _documents_module()
    documents_module.DatasetService.ensure_member(db, tenant_id, account_id)

    updated = 0
    not_found: list[UUID] = []
    denied: list[UUID] = []
    conflicts: list[UUID] = []

    for document_id in payload.document_ids:
        doc = documents_module._get_document_for_lifecycle(db, tenant_id, document_id)
        if not doc:
            not_found.append(document_id)
            continue
        try:
            documents_module._assert_document_writable_for_lifecycle(
                db,
                tenant_id=tenant_id,
                account_id=account_id,
                document=doc,
            )
        except HTTPException:
            denied.append(document_id)
            continue

        if getattr(doc, "disabled_at", None) is not None:
            doc.disabled_at = None
            updated += 1

            documents_module.audit_log_event(
                db,
                tenant_id=tenant_id,
                actor_id=account_id,
                action="document.enable",
                resource_type="document",
                resource_id=str(document_id),
                details={"disabled_at": None},
            )

    if updated:
        db.commit()

    return {"updated": updated, "not_found": not_found, "denied": denied, "conflicts": conflicts}


@router.post("/batch/archive", response_model=DocumentBatchLifecycleResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def batch_archive_documents(
    payload: DocumentBatchLifecycleRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """Batch archive documents (best-effort)."""
    documents_module = _documents_module()
    documents_module.DatasetService.ensure_member(db, tenant_id, account_id)

    updated = 0
    not_found: list[UUID] = []
    denied: list[UUID] = []
    conflicts: list[UUID] = []

    now = datetime.now(UTC)

    for document_id in payload.document_ids:
        doc = documents_module._get_document_for_lifecycle(db, tenant_id, document_id)
        if not doc:
            not_found.append(document_id)
            continue
        try:
            documents_module._assert_document_writable_for_lifecycle(
                db,
                tenant_id=tenant_id,
                account_id=account_id,
                document=doc,
            )
        except HTTPException:
            denied.append(document_id)
            continue

        if getattr(doc, "archived_at", None) is None:
            doc.archived_at = now
            updated += 1

            documents_module.audit_log_event(
                db,
                tenant_id=tenant_id,
                actor_id=account_id,
                action="document.archive",
                resource_type="document",
                resource_id=str(document_id),
                details={"archived_at": now.isoformat()},
            )

    if updated:
        db.commit()

    return {"updated": updated, "not_found": not_found, "denied": denied, "conflicts": conflicts}


@router.post("/batch/unarchive", response_model=DocumentBatchLifecycleResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def batch_unarchive_documents(
    payload: DocumentBatchLifecycleRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """Batch unarchive documents (best-effort)."""
    documents_module = _documents_module()
    documents_module.DatasetService.ensure_member(db, tenant_id, account_id)

    updated = 0
    not_found: list[UUID] = []
    denied: list[UUID] = []
    conflicts: list[UUID] = []

    for document_id in payload.document_ids:
        doc = documents_module._get_document_for_lifecycle(db, tenant_id, document_id)
        if not doc:
            not_found.append(document_id)
            continue
        try:
            documents_module._assert_document_writable_for_lifecycle(
                db,
                tenant_id=tenant_id,
                account_id=account_id,
                document=doc,
            )
        except HTTPException:
            denied.append(document_id)
            continue

        if getattr(doc, "archived_at", None) is not None:
            doc.archived_at = None
            updated += 1

            documents_module.audit_log_event(
                db,
                tenant_id=tenant_id,
                actor_id=account_id,
                action="document.unarchive",
                resource_type="document",
                resource_id=str(document_id),
                details={"archived_at": None},
            )

    if updated:
        db.commit()

    return {"updated": updated, "not_found": not_found, "denied": denied, "conflicts": conflicts}


@router.post("/batch-delete", response_model=DocumentBatchDeleteResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def batch_delete_documents(
    payload: DocumentBatchDeleteRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Batch delete documents (best-effort per id).
    """
    documents_module = _documents_module()
    documents_module.DatasetService.ensure_member(db, tenant_id, account_id)

    deleted = 0
    not_found: list[UUID] = []
    denied: list[UUID] = []

    for document_id in payload.document_ids:
        try:
            await documents_module.delete_document(
                document_id=document_id,
                tenant_id=tenant_id,
                account_id=account_id,
                db=db,
            )
            deleted += 1
        except HTTPException as exc:
            if exc.status_code == 404:
                not_found.append(document_id)
                continue
            if exc.status_code in (401, 403):
                denied.append(document_id)
                continue
            raise

    return {"deleted": deleted, "not_found": not_found, "denied": denied}

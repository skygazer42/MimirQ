from datetime import UTC, datetime
from typing import Annotated, Literal
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
from app.services import dataset_service
from app.services.audit_log_service import audit_log_event
from app.services.document_access_service import (
    assert_document_writable_for_lifecycle,
    get_document_for_lifecycle,
)
from app.services.document_lifecycle_service import _delete_document_lifecycle

_DEFAULT_HTTP_EXCEPTION_RESPONSES = {
    400: {"description": "Bad Request"},
    403: {"description": "Forbidden"},
    404: {"description": "Not Found"},
    409: {"description": "Conflict"},
    416: {"description": "Range Not Satisfiable"},
}

router = APIRouter(responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)


@router.post(
    "/batch/disable", response_model=DocumentBatchLifecycleResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES
)
def batch_disable_documents(
    payload: DocumentBatchLifecycleRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, int | list[UUID]]:
    """Batch disable documents (best-effort)."""
    return _update_document_lifecycle_state(
        payload,
        tenant_id=tenant_id,
        account_id=account_id,
        db=db,
        state_field="disabled_at",
        audit_action="document.disable",
        set_timestamp=True,
    )


@router.post(
    "/batch/enable", response_model=DocumentBatchLifecycleResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES
)
def batch_enable_documents(
    payload: DocumentBatchLifecycleRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, int | list[UUID]]:
    """Batch enable documents (best-effort)."""
    return _update_document_lifecycle_state(
        payload,
        tenant_id=tenant_id,
        account_id=account_id,
        db=db,
        state_field="disabled_at",
        audit_action="document.enable",
        set_timestamp=False,
    )


@router.post(
    "/batch/archive", response_model=DocumentBatchLifecycleResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES
)
def batch_archive_documents(
    payload: DocumentBatchLifecycleRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, int | list[UUID]]:
    """Batch archive documents (best-effort)."""
    return _update_document_lifecycle_state(
        payload,
        tenant_id=tenant_id,
        account_id=account_id,
        db=db,
        state_field="archived_at",
        audit_action="document.archive",
        set_timestamp=True,
    )


@router.post(
    "/batch/unarchive", response_model=DocumentBatchLifecycleResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES
)
def batch_unarchive_documents(
    payload: DocumentBatchLifecycleRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, int | list[UUID]]:
    """Batch unarchive documents (best-effort)."""
    return _update_document_lifecycle_state(
        payload,
        tenant_id=tenant_id,
        account_id=account_id,
        db=db,
        state_field="archived_at",
        audit_action="document.unarchive",
        set_timestamp=False,
    )


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
    dataset_service.ensure_member(db, tenant_id, account_id)

    deleted = 0
    not_found: list[UUID] = []
    denied: list[UUID] = []

    for document_id in payload.document_ids:
        try:
            await _delete_document_lifecycle(
                document_id=document_id,
                tenant_id=tenant_id,
                account_id=account_id,
                db=db,
                enforce_permissions=True,
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


def _update_document_lifecycle_state(
    payload: DocumentBatchLifecycleRequest,
    *,
    tenant_id: UUID,
    account_id: str,
    db: Session,
    state_field: Literal["disabled_at", "archived_at"],
    audit_action: Literal["document.disable", "document.enable", "document.archive", "document.unarchive"],
    set_timestamp: bool,
) -> dict[str, int | list[UUID]]:
    dataset_service.ensure_member(db, tenant_id, account_id)

    updated = 0
    not_found: list[UUID] = []
    denied: list[UUID] = []
    conflicts: list[UUID] = []
    timestamp = datetime.now(UTC) if set_timestamp else None

    for document_id in payload.document_ids:
        document = get_document_for_lifecycle(db, tenant_id, document_id)
        if document is None:
            not_found.append(document_id)
            continue

        try:
            assert_document_writable_for_lifecycle(
                db,
                tenant_id=tenant_id,
                account_id=account_id,
                document=document,
            )
        except HTTPException:
            denied.append(document_id)
            continue

        current_timestamp = document.disabled_at if state_field == "disabled_at" else document.archived_at
        if (set_timestamp and current_timestamp is not None) or (not set_timestamp and current_timestamp is None):
            continue

        if state_field == "disabled_at":
            document.disabled_at = timestamp
        else:
            document.archived_at = timestamp
        updated += 1

        audit_log_event(
            db,
            tenant_id=tenant_id,
            actor_id=account_id,
            action=audit_action,
            resource_type="document",
            resource_id=str(document_id),
            details={state_field: timestamp.isoformat() if timestamp is not None else None},
        )

    if updated:
        db.commit()

    return {"updated": updated, "not_found": not_found, "denied": denied, "conflicts": conflicts}

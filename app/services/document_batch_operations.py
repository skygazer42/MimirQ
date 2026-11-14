"""Tenant-scoped best-effort document batch operations."""

from uuid import UUID

from fastapi import BackgroundTasks, HTTPException
from sqlalchemy.orm import Session

from app.api.schemas.documents import (
    DocumentBatchAccessUpdateRequest,
    DocumentBatchAccessUpdateResponse,
    DocumentBatchMoveRequest,
    DocumentBatchMoveResponse,
    DocumentBatchReingestRequest,
    DocumentBatchRetryRequest,
    DocumentBatchRetryResponse,
    DocumentBatchUserMetadataPatchRequest,
    DocumentBatchUserMetadataPatchResponse,
    DocumentPipelinePatchRequest,
)
from app.models.document import Document as DBDocument
from app.models.tenant import TenantMember
from app.services import (
    dataset_service,
    document_access_service,
    document_metadata_operations,
    document_processing_operations,
)
from app.services.dataset_service import EDIT_ROLES
from app.services.document_user_metadata import apply_user_metadata_patch
from app.storage.object.runtime import is_object_storage_uri


def _record_batch_http_error(
    *,
    exc: HTTPException,
    document_id: UUID,
    not_found: list[UUID],
    denied: list[UUID],
    conflicts: list[UUID],
) -> bool:
    if exc.status_code == 404:
        not_found.append(document_id)
        return True
    if exc.status_code in (401, 403):
        denied.append(document_id)
        return True
    if exc.status_code in (409, 413, 429, 503):
        conflicts.append(document_id)
        return True
    return False


def patch_user_metadata(
    *,
    payload: DocumentBatchUserMetadataPatchRequest,
    db: Session,
    tenant_id: UUID,
    account_id: str,
) -> DocumentBatchUserMetadataPatchResponse:
    dataset_service.ensure_member(db, tenant_id, account_id)
    document_ids = payload.document_ids
    documents = db.query(DBDocument).filter(DBDocument.tenant_id == tenant_id, DBDocument.id.in_(document_ids)).all()
    found = {document.id for document in documents}
    not_found = [document_id for document_id in document_ids if document_id not in found]
    denied: list[UUID] = []
    updated = 0

    for document in documents:
        try:
            document_access_service.assert_document_writable_for_lifecycle(
                db,
                tenant_id=tenant_id,
                account_id=account_id,
                document=document,
            )
        except HTTPException:
            denied.append(document.id)
            continue

        metadata = dict(document.doc_metadata or {})
        current = metadata.get("user") if isinstance(metadata.get("user"), dict) else {}
        metadata["user"] = apply_user_metadata_patch(current=current, patch=payload.patch, replace=payload.replace)
        document.doc_metadata = metadata
        updated += 1

    if updated:
        db.commit()
    return DocumentBatchUserMetadataPatchResponse(updated=updated, not_found=not_found, denied=denied)


async def _retry_document(
    *,
    document_id: UUID,
    payload: DocumentBatchRetryRequest | DocumentBatchReingestRequest,
    background_tasks: BackgroundTasks,
    db: Session,
    tenant_id: UUID,
    account_id: str,
) -> str:
    result = await document_processing_operations.retry_document(
        document_id=document_id,
        background_tasks=background_tasks,
        force=payload.force,
        skip_if_unchanged=payload.skip_if_unchanged,
        tenant_id=tenant_id,
        account_id=account_id,
        db=db,
    )
    return result.status


async def retry_documents(
    *,
    payload: DocumentBatchRetryRequest,
    background_tasks: BackgroundTasks,
    db: Session,
    tenant_id: UUID,
    account_id: str,
) -> DocumentBatchRetryResponse:
    dataset_service.ensure_member(db, tenant_id, account_id)
    queued = 0
    skipped = 0
    not_found: list[UUID] = []
    denied: list[UUID] = []
    conflicts: list[UUID] = []

    for document_id in payload.document_ids:
        try:
            status = await _retry_document(
                document_id=document_id,
                payload=payload,
                background_tasks=background_tasks,
                db=db,
                tenant_id=tenant_id,
                account_id=account_id,
            )
            if payload.force and payload.skip_if_unchanged and status == "completed":
                skipped += 1
            else:
                queued += 1
        except HTTPException as exc:
            if not _record_batch_http_error(
                exc=exc,
                document_id=document_id,
                not_found=not_found,
                denied=denied,
                conflicts=conflicts,
            ):
                raise

    return DocumentBatchRetryResponse(
        queued=queued,
        skipped=skipped,
        not_found=not_found,
        denied=denied,
        conflicts=conflicts,
    )


async def reingest_documents(
    *,
    payload: DocumentBatchReingestRequest,
    background_tasks: BackgroundTasks,
    db: Session,
    tenant_id: UUID,
    account_id: str,
) -> DocumentBatchRetryResponse:
    dataset_service.ensure_member(db, tenant_id, account_id)
    patch_request = DocumentPipelinePatchRequest(patch=payload.patch, replace=payload.replace)
    has_patch = bool(payload.patch.model_fields_set)
    queued = 0
    skipped = 0
    not_found: list[UUID] = []
    denied: list[UUID] = []
    conflicts: list[UUID] = []

    for document_id in payload.document_ids:
        if payload.replace or has_patch:
            try:
                document_metadata_operations.patch_pipeline(
                    document_id=document_id,
                    payload=patch_request,
                    db=db,
                    tenant_id=tenant_id,
                    account_id=account_id,
                )
            except HTTPException as exc:
                if _record_batch_http_error(
                    exc=exc,
                    document_id=document_id,
                    not_found=not_found,
                    denied=denied,
                    conflicts=conflicts,
                ):
                    continue
                raise

        try:
            status = await _retry_document(
                document_id=document_id,
                payload=payload,
                background_tasks=background_tasks,
                db=db,
                tenant_id=tenant_id,
                account_id=account_id,
            )
            if payload.force and payload.skip_if_unchanged and status == "completed":
                skipped += 1
            else:
                queued += 1
        except HTTPException as exc:
            if not _record_batch_http_error(
                exc=exc,
                document_id=document_id,
                not_found=not_found,
                denied=denied,
                conflicts=conflicts,
            ):
                raise

    return DocumentBatchRetryResponse(
        queued=queued,
        skipped=skipped,
        not_found=not_found,
        denied=denied,
        conflicts=conflicts,
    )


def update_document_access(
    *,
    payload: DocumentBatchAccessUpdateRequest,
    db: Session,
    tenant_id: UUID,
    account_id: str,
) -> DocumentBatchAccessUpdateResponse:
    dataset_service.ensure_member(db, tenant_id, account_id)
    updated = 0
    not_found: list[UUID] = []
    denied: list[UUID] = []

    for document_id in payload.document_ids:
        try:
            document_access_service.update_document_access(
                document_id=document_id,
                payload=payload.access,
                db=db,
                tenant_id=tenant_id,
                account_id=account_id,
            )
            updated += 1
        except HTTPException as exc:
            if exc.status_code == 404:
                not_found.append(document_id)
                continue
            if exc.status_code in (401, 403):
                denied.append(document_id)
                continue
            raise

    return DocumentBatchAccessUpdateResponse(updated=updated, not_found=not_found, denied=denied)


def _resolve_batch_move_target(
    *,
    db: Session,
    tenant_id: UUID,
    account_id: str,
    payload: DocumentBatchMoveRequest,
) -> TenantMember:
    member = dataset_service.ensure_member(db, tenant_id, account_id)
    if payload.target_dataset_id is not None:
        target = dataset_service.get_dataset(db, tenant_id, payload.target_dataset_id)
        dataset_service.assert_dataset_writable(db, target, account_id)
        return member
    if member.role.lower() not in EDIT_ROLES:
        raise HTTPException(status_code=403, detail="No permission to move documents to unassigned scope")
    return member


def _move_document_conflicts(document: DBDocument) -> bool:
    if (document.status).lower() in {"pending", "processing"}:
        return True
    raw_path = (document.file_path).strip()
    if raw_path and is_object_storage_uri(raw_path):
        return True
    image_ids = (document.doc_metadata or {}).get("img_ids")
    return isinstance(image_ids, list) and any(isinstance(value, str) and value.strip() for value in image_ids)


def move_documents(
    *,
    payload: DocumentBatchMoveRequest,
    db: Session,
    tenant_id: UUID,
    account_id: str,
) -> DocumentBatchMoveResponse:
    _resolve_batch_move_target(
        db=db,
        tenant_id=tenant_id,
        account_id=account_id,
        payload=payload,
    )

    documents = (
        db.query(DBDocument)
        .filter(
            DBDocument.tenant_id == tenant_id,
            DBDocument.id.in_(payload.document_ids),
        )
        .all()
    )
    found = {document.id: document for document in documents}
    not_found = [document_id for document_id in payload.document_ids if document_id not in found]
    denied: list[UUID] = []
    conflicts: list[UUID] = []
    moved = 0

    for document in documents:
        try:
            document_access_service.assert_document_writable_for_lifecycle(
                db,
                tenant_id=tenant_id,
                account_id=account_id,
                document=document,
            )
        except HTTPException:
            denied.append(document.id)
            continue
        if payload.target_dataset_id is None:
            try:
                document_access_service.assert_document_writable_for_unassigned_target(
                    db,
                    tenant_id=tenant_id,
                    account_id=account_id,
                    document=document,
                )
            except HTTPException:
                denied.append(document.id)
                continue
        if _move_document_conflicts(document):
            conflicts.append(document.id)
            continue
        document.dataset_id = payload.target_dataset_id
        moved += 1

    if moved:
        db.commit()
    return DocumentBatchMoveResponse(moved=moved, not_found=not_found, denied=denied, conflicts=conflicts)


__all__ = [
    "move_documents",
    "patch_user_metadata",
    "reingest_documents",
    "retry_documents",
    "update_document_access",
]

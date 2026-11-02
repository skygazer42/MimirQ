from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.api.schemas.document import (
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
from app.api.v1 import document_access, document_mutations, document_processing
from app.core.database import get_db
from app.models.document import Document as DBDocument
from app.services import dataset_service, document_access_service
from app.services.dataset_service import EDIT_ROLES
from app.services.document_metadata_service import apply_user_metadata_patch
from app.storage.object.runtime import is_object_storage_uri

_DEFAULT_HTTP_EXCEPTION_RESPONSES = {
    400: {"description": "Bad Request"},
    403: {"description": "Forbidden"},
    404: {"description": "Not Found"},
    409: {"description": "Conflict"},
    416: {"description": "Range Not Satisfiable"},
}

router = APIRouter(responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)


@router.post(
    "/batch/metadata",
    response_model=DocumentBatchUserMetadataPatchResponse,
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
def batch_patch_document_user_metadata(
    payload: DocumentBatchUserMetadataPatchRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """
    Batch patch `documents.metadata.user`.

    For any documents the caller cannot write, they will be returned in `denied`.
    """
    dataset_service.ensure_member(db, tenant_id, account_id)

    ids = payload.document_ids

    documents = db.query(DBDocument).filter(DBDocument.tenant_id == tenant_id, DBDocument.id.in_(ids)).all()
    found_map = {document.id: document for document in documents}
    not_found = [document_id for document_id in ids if document_id not in found_map]

    denied: list[UUID] = []
    updated = 0

    patch = payload.patch
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

        meta = dict(document.doc_metadata or {})
        current_user = meta.get("user") if isinstance(meta.get("user"), dict) else {}
        next_user = apply_user_metadata_patch(current=current_user, patch=patch, replace=payload.replace)
        meta["user"] = next_user
        document.doc_metadata = meta
        updated += 1

    if updated:
        db.commit()

    return {"updated": updated, "not_found": not_found, "denied": denied}


@router.post("/batch/retry", response_model=DocumentBatchRetryResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def batch_retry_documents(
    payload: DocumentBatchRetryRequest,
    background_tasks: BackgroundTasks,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """Batch retry/reprocess documents (best-effort per id)."""
    dataset_service.ensure_member(db, tenant_id, account_id)

    queued = 0
    skipped = 0
    not_found: list[UUID] = []
    denied: list[UUID] = []
    conflicts: list[UUID] = []

    for document_id in payload.document_ids:
        try:
            out = await document_processing.retry_document_processing(
                document_id=document_id,
                background_tasks=background_tasks,
                force=payload.force,
                skip_if_unchanged=payload.skip_if_unchanged,
                tenant_id=tenant_id,
                account_id=account_id,
                db=db,
            )
            status = out["status"].lower()
            if payload.force and payload.skip_if_unchanged and status == "completed":
                skipped += 1
            else:
                queued += 1
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

    return {
        "queued": queued,
        "skipped": skipped,
        "not_found": not_found,
        "denied": denied,
        "conflicts": conflicts,
    }


@router.post("/batch/reingest", response_model=DocumentBatchRetryResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def batch_reingest_documents(
    payload: DocumentBatchReingestRequest,
    background_tasks: BackgroundTasks,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """
    Batch re-ingest documents by (optionally) patching pipeline overrides and forcing a retry.

    Notes:
    - This is best-effort per id: failures are returned in `not_found/denied/conflicts`.
    - Intended for generating new pipeline_hash versions and/or rebuilding indexes.
    """
    dataset_service.ensure_member(db, tenant_id, account_id)

    queued = 0
    skipped = 0
    not_found: list[UUID] = []
    denied: list[UUID] = []
    conflicts: list[UUID] = []

    patch_req = DocumentPipelinePatchRequest(patch=payload.patch, replace=payload.replace)
    has_patch = bool(payload.patch.model_fields_set)

    for document_id in payload.document_ids:
        if payload.replace or has_patch:
            try:
                document_mutations.patch_document_pipeline(
                    document_id=document_id,
                    payload=patch_req,
                    tenant_id=tenant_id,
                    account_id=account_id,
                    db=db,
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
            out = await document_processing.retry_document_processing(
                document_id=document_id,
                background_tasks=background_tasks,
                force=payload.force,
                skip_if_unchanged=payload.skip_if_unchanged,
                tenant_id=tenant_id,
                account_id=account_id,
                db=db,
            )
            if payload.force and payload.skip_if_unchanged and out["status"].lower() == "completed":
                skipped += 1
            else:
                queued += 1
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

    return {
        "queued": queued,
        "skipped": skipped,
        "not_found": not_found,
        "denied": denied,
        "conflicts": conflicts,
    }


@router.post(
    "/batch/access", response_model=DocumentBatchAccessUpdateResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES
)
async def batch_update_document_access(
    payload: DocumentBatchAccessUpdateRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """Batch update document ACL (best-effort per id)."""
    dataset_service.ensure_member(db, tenant_id, account_id)

    updated = 0
    not_found: list[UUID] = []
    denied: list[UUID] = []

    for document_id in payload.document_ids:
        try:
            await document_access.put_document_access(
                document_id=document_id,
                payload=payload.access,
                tenant_id=tenant_id,
                account_id=account_id,
                db=db,
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

    return {"updated": updated, "not_found": not_found, "denied": denied}


@router.post("/batch/move", response_model=DocumentBatchMoveResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def batch_move_documents(
    payload: DocumentBatchMoveRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """
    Batch move documents between datasets (best-effort).

    Notes:
    - Disallows moving MinIO-backed documents or documents with MinIO image assets (`metadata.img_ids`)
      because dataset_id is part of the object/key namespace.
    - Disallows moving documents that are pending/processing.
    """
    _resolve_batch_move_target(
        db=db,
        tenant_id=tenant_id,
        account_id=account_id,
        payload=payload,
    )

    moved = 0
    not_found: list[UUID] = []
    denied: list[UUID] = []
    conflicts: list[UUID] = []

    for document_id in payload.document_ids:
        doc = db.query(DBDocument).filter(DBDocument.id == document_id, DBDocument.tenant_id == tenant_id).first()
        if not doc:
            not_found.append(document_id)
            continue

        try:
            document_access_service.assert_document_writable_for_lifecycle(
                db,
                tenant_id=tenant_id,
                account_id=account_id,
                document=doc,
            )
        except HTTPException:
            denied.append(document_id)
            continue
        if payload.target_dataset_id is None:
            try:
                document_access_service.assert_document_writable_for_unassigned_target(
                    db,
                    tenant_id=tenant_id,
                    account_id=account_id,
                    document=doc,
                )
            except HTTPException:
                denied.append(document_id)
                continue
        if _move_document_conflicts(doc=doc):
            conflicts.append(document_id)
            continue

        doc.dataset_id = payload.target_dataset_id
        moved += 1

    if moved:
        db.commit()

    return {"moved": moved, "not_found": not_found, "denied": denied, "conflicts": conflicts}


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


def _resolve_batch_move_target(
    *,
    db: Session,
    tenant_id: UUID,
    account_id: str,
    payload: DocumentBatchMoveRequest,
) -> None:
    member = dataset_service.ensure_member(db, tenant_id, account_id)
    if payload.target_dataset_id is not None:
        target_ds = dataset_service.get_dataset(db, tenant_id, payload.target_dataset_id)
        dataset_service.assert_dataset_writable(db, target_ds, account_id)
        return
    role = (member.role or "").lower()
    if role not in EDIT_ROLES:
        raise HTTPException(status_code=403, detail="No permission to move documents to unassigned scope")


def _move_document_conflicts(*, doc: DBDocument) -> bool:
    status = doc.status.lower()
    if status in {"pending", "processing"}:
        return True
    raw_path = doc.file_path.strip()
    if raw_path and is_object_storage_uri(raw_path):
        return True
    meta = dict(doc.doc_metadata or {})
    img_ids = meta.get("img_ids")
    return isinstance(img_ids, list) and any(isinstance(value, str) and value.strip() for value in img_ids)

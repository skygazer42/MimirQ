from __future__ import annotations

import importlib
from typing import Annotated
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
from app.core.database import get_db
from app.models.dataset import Dataset
from app.models.document import Document as DBDocument

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


@router.post("/batch/metadata", response_model=DocumentBatchUserMetadataPatchResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def batch_patch_document_user_metadata(
    payload: DocumentBatchUserMetadataPatchRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Batch patch `documents.metadata.user`.

    For any documents the caller cannot write, they will be returned in `denied`.
    """
    documents_module = _documents_module()
    documents_module.DatasetService.ensure_member(db, tenant_id, account_id)

    ids = list(payload.document_ids or [])
    if not ids:
        return {"updated": 0, "not_found": [], "denied": []}

    documents = (
        db.query(DBDocument)
        .filter(DBDocument.tenant_id == tenant_id, DBDocument.id.in_(ids))
        .all()
    )
    found_map = {document.id: document for document in documents}
    not_found = [document_id for document_id in ids if document_id not in found_map]

    dataset_ids = {document.dataset_id for document in documents if document.dataset_id is not None}
    dataset_map: dict[UUID, Dataset] = {}
    if dataset_ids:
        rows = (
            db.query(Dataset)
            .filter(Dataset.tenant_id == tenant_id, Dataset.id.in_(sorted(dataset_ids)))
            .all()
        )
        dataset_map = {dataset.id: dataset for dataset in rows}

    denied: list[UUID] = []
    updated = 0

    patch = payload.patch if isinstance(payload.patch, dict) else {}
    for document in documents:
        if document.dataset_id:
            dataset = dataset_map.get(document.dataset_id)
            if dataset is None:
                denied.append(document.id)
                continue
            try:
                documents_module.DatasetService.assert_dataset_writable(db, dataset, account_id)
            except HTTPException:
                denied.append(document.id)
                continue

        meta = dict(document.doc_metadata or {})
        current_user = meta.get("user") if isinstance(meta.get("user"), dict) else {}
        next_user = documents_module._apply_user_metadata_patch(current=current_user, patch=patch, replace=payload.replace)
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
):
    """Batch retry/reprocess documents (best-effort per id)."""
    documents_module = _documents_module()
    documents_module.DatasetService.ensure_member(db, tenant_id, account_id)

    queued = 0
    skipped = 0
    not_found: list[UUID] = []
    denied: list[UUID] = []
    conflicts: list[UUID] = []

    for document_id in payload.document_ids:
        try:
            out = await documents_module.retry_document_processing(
                document_id=document_id,
                background_tasks=background_tasks,
                force=bool(payload.force),
                skip_if_unchanged=bool(payload.skip_if_unchanged),
                tenant_id=tenant_id,
                account_id=account_id,
                db=db,
            )
            status = str((out or {}).get("status") or "").lower()
            if bool(payload.force) and bool(payload.skip_if_unchanged) and status == "completed":
                skipped += 1
            else:
                queued += 1
        except HTTPException as exc:
            if exc.status_code == 404:
                not_found.append(document_id)
                continue
            if exc.status_code in (401, 403):
                denied.append(document_id)
                continue
            if exc.status_code in (409, 413, 429, 503):
                conflicts.append(document_id)
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
):
    """
    Batch re-ingest documents by (optionally) patching pipeline overrides and forcing a retry.

    Notes:
    - This is best-effort per id: failures are returned in `not_found/denied/conflicts`.
    - Intended for generating new pipeline_hash versions and/or rebuilding indexes.
    """
    documents_module = _documents_module()
    documents_module.DatasetService.ensure_member(db, tenant_id, account_id)

    queued = 0
    skipped = 0
    not_found: list[UUID] = []
    denied: list[UUID] = []
    conflicts: list[UUID] = []

    patch_req = DocumentPipelinePatchRequest(patch=payload.patch, replace=bool(payload.replace))
    has_patch = bool(getattr(payload.patch, "model_fields_set", set()))

    for document_id in payload.document_ids:
        if bool(payload.replace) or has_patch:
            try:
                await documents_module.patch_document_pipeline(
                    document_id=document_id,
                    payload=patch_req,
                    tenant_id=tenant_id,
                    account_id=account_id,
                    db=db,
                )
            except HTTPException as exc:
                if exc.status_code == 404:
                    not_found.append(document_id)
                    continue
                if exc.status_code in (401, 403):
                    denied.append(document_id)
                    continue
                if exc.status_code in (409, 413, 429, 503):
                    conflicts.append(document_id)
                    continue
                raise

        try:
            out = await documents_module.retry_document_processing(
                document_id=document_id,
                background_tasks=background_tasks,
                force=bool(payload.force),
                skip_if_unchanged=bool(payload.skip_if_unchanged),
                tenant_id=tenant_id,
                account_id=account_id,
                db=db,
            )
            status = str((out or {}).get("status") or "").lower()
            if bool(payload.force) and bool(payload.skip_if_unchanged) and status == "completed":
                skipped += 1
            else:
                queued += 1
        except HTTPException as exc:
            if exc.status_code == 404:
                not_found.append(document_id)
                continue
            if exc.status_code in (401, 403):
                denied.append(document_id)
                continue
            if exc.status_code in (409, 413, 429, 503):
                conflicts.append(document_id)
                continue
            raise

    return {
        "queued": queued,
        "skipped": skipped,
        "not_found": not_found,
        "denied": denied,
        "conflicts": conflicts,
    }


@router.post("/batch/access", response_model=DocumentBatchAccessUpdateResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def batch_update_document_access(
    payload: DocumentBatchAccessUpdateRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """Batch update document ACL (best-effort per id)."""
    documents_module = _documents_module()
    documents_module.DatasetService.ensure_member(db, tenant_id, account_id)

    updated = 0
    not_found: list[UUID] = []
    denied: list[UUID] = []

    for document_id in payload.document_ids:
        try:
            await documents_module.put_document_access(
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
async def batch_move_documents(
    payload: DocumentBatchMoveRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Batch move documents between datasets (best-effort).

    Notes:
    - Disallows moving MinIO-backed documents or documents with MinIO image assets (`metadata.img_ids`)
      because dataset_id is part of the object/key namespace.
    - Disallows moving documents that are pending/processing.
    """
    documents_module = _documents_module()
    member = documents_module.DatasetService.ensure_member(db, tenant_id, account_id)

    target_ds: Dataset | None = None
    if payload.target_dataset_id is not None:
        target_ds = documents_module.DatasetService.get_dataset(db, tenant_id, payload.target_dataset_id)
        documents_module.DatasetService.assert_dataset_writable(db, target_ds, account_id)
    else:
        role = (getattr(member, "role", None) or "").lower()
        if role not in documents_module.EDIT_ROLES:
            raise HTTPException(status_code=403, detail="No permission to move documents to unassigned scope")

    moved = 0
    not_found: list[UUID] = []
    denied: list[UUID] = []
    conflicts: list[UUID] = []

    for document_id in payload.document_ids:
        doc = (
            db.query(DBDocument)
            .filter(DBDocument.id == document_id, DBDocument.tenant_id == tenant_id)
            .first()
        )
        if not doc:
            not_found.append(document_id)
            continue

        if doc.dataset_id:
            try:
                dataset = documents_module.DatasetService.get_dataset(db, tenant_id, doc.dataset_id)
                documents_module.DatasetService.assert_dataset_writable(db, dataset, account_id)
            except HTTPException:
                denied.append(document_id)
                continue

        status = str(doc.status or "").lower()
        if status in {"pending", "processing"}:
            conflicts.append(document_id)
            continue

        raw_path = str(getattr(doc, "file_path", "") or "").strip()
        if raw_path and documents_module.is_minio_uri(raw_path):
            conflicts.append(document_id)
            continue

        meta = dict(getattr(doc, "doc_metadata", None) or {})
        img_ids = meta.get("img_ids")
        if isinstance(img_ids, list) and any(isinstance(value, str) and value.strip() for value in img_ids):
            conflicts.append(document_id)
            continue

        doc.dataset_id = payload.target_dataset_id
        moved += 1

    if moved:
        db.commit()

    return {"moved": moved, "not_found": not_found, "denied": denied, "conflicts": conflicts}

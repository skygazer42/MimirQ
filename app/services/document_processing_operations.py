"""Document status, cancellation and reprocessing business operations."""

import asyncio
import contextlib
import uuid
from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi import BackgroundTasks, HTTPException
from sqlalchemy.orm import Session

from app.api.schemas.document import DocumentStatus
from app.core.config import settings
from app.models.document import Document as DBDocument
from app.models.document import DocumentChunk
from app.parsing.factory import parser_factory
from app.rag.core.logging import get_logger
from app.services import dataset_service
from app.services.audit_log_service import audit_log_event
from app.services.document_access_service import (
    assert_document_readable_for_lifecycle,
    assert_document_writable_for_lifecycle,
)
from app.services.document_identity import compute_pipeline_hash, get_content_sha256, sync_pipeline_execution_identity
from app.services.document_index_channel_service import reconcile_document_index_channels
from app.services.document_lifecycle_service import DOC_NOT_FOUND_DETAIL, MANUAL_FILE_PATH_PREFIX
from app.services.document_processing_dispatch import dispatch_retry_document, resolve_retry_source

logger = get_logger("services.document_processing_operations")


def _is_uploaded_only_pending_document(document: DBDocument) -> bool:
    """
    True for files registered by upload-only mode but not yet queued/processed.

    Those documents are persisted as `status=pending` so they appear in ingestion
    lists, but they are not active processing jobs. Reingest may safely patch
    their pipeline and start processing them later.
    """
    if str(document.status or "").strip().lower() != "pending":
        return False

    meta = document.doc_metadata or {}
    if str(meta.get("ingest_stage") or "").strip() != "uploaded_only":
        return False
    if str(meta.get("task_id") or "").strip():
        return False

    current_stage = str(document.current_stage or "").strip().lower()
    if current_stage and current_stage not in {"uploaded_only", "registered"}:
        return False

    return not bool(meta.get("active_pipeline_ready"))


def _is_idle_pending_document(document: DBDocument) -> bool:
    """
    True for pending documents that are persisted but not attached to a live job.

    Legacy imports and upload-only flows can leave a document as `status=pending`
    without `ingest_stage=uploaded_only`. They are safe to reconfigure only when
    no queue/task marker, active stage, or progress indicates work is running.
    """
    if str(document.status or "").strip().lower() != "pending":
        return False

    meta = document.doc_metadata or {}
    if str(meta.get("task_id") or "").strip() or str(meta.get("kg_task_id") or "").strip():
        return False

    current_stage = str(document.current_stage or "").strip().lower()
    if current_stage and current_stage not in {"uploaded_only", "registered"}:
        return False

    progress = document.processing_progress or 0
    if progress > 0:
        return False

    return not bool(meta.get("active_pipeline_ready"))


def is_reprocessable_pending_document(document: DBDocument) -> bool:
    return _is_uploaded_only_pending_document(document) or _is_idle_pending_document(document)


def _document_status_payload(document: DBDocument) -> DocumentStatus:
    return DocumentStatus.model_validate(
        {
            "id": document.id,
            "status": document.status,
            "processing_progress": document.processing_progress,
            "current_stage": document.current_stage,
            "failed_stage": document.failed_stage,
            "error_code": document.error_code,
            "processing_attempts": document.processing_attempts,
            "next_retry_at": document.next_retry_at,
            "error_message": document.error_message,
        }
    )


def read_document_status(
    *,
    document_id: UUID,
    tenant_id: UUID,
    account_id: str,
    db: Session,
) -> DocumentStatus:
    """
    Get document processing status (for polling).
    """
    dataset_service.ensure_member(db, tenant_id, account_id)
    document = _get_document(db=db, document_id=document_id, tenant_id=tenant_id)

    assert_document_readable_for_lifecycle(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        document=document,
    )

    return _document_status_payload(document)


async def cancel_document(
    *,
    document_id: UUID,
    tenant_id: UUID,
    account_id: str,
    db: Session,
) -> DocumentStatus:
    """
    Cancel an in-progress document processing task.

    Notes:
    - When TASK_QUEUE_ENABLED=true, this will best-effort abort the arq job.
    - When queue is disabled, the in-process/background worker cooperatively checks the cancelled status.
    """
    dataset_service.ensure_member(db, tenant_id, account_id)

    document = _get_document(db=db, document_id=document_id, tenant_id=tenant_id)

    assert_document_writable_for_lifecycle(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        document=document,
    )

    current_status = str(document.status or "").lower()
    if current_status in {"completed", "failed"}:
        raise HTTPException(status_code=409, detail=f"Cannot cancel a {current_status} document")

    meta = dict(document.doc_metadata or {})
    meta["cancel_requested"] = True
    document.doc_metadata = meta
    document.status = "cancelled"
    document.processing_progress = 0
    document.current_stage = "cancelled"
    document.error_message = "cancelled"
    db.commit()
    db.refresh(document)

    task_id = meta.get("task_id")
    kg_task_id = meta.get("kg_task_id")
    task_ids: list[str] = []
    for raw in (task_id, kg_task_id):
        if isinstance(raw, str) and raw.strip():
            task_ids.append(raw.strip())

    if settings.TASK_QUEUE_ENABLED and task_ids:
        from arq.jobs import Job

        from app.tasks.queue import get_queue

        try:
            queue = await get_queue()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Failed to access task queue while aborting tasks %s for document %s: %s",
                task_ids,
                document_id,
                str(exc)[:200],
            )
        else:
            if queue is not None:
                queue_name = settings.TASK_QUEUE_NAME
                for task in task_ids:
                    job = Job(task, queue, _queue_name=queue_name)
                    with contextlib.suppress(TimeoutError, asyncio.TimeoutError):
                        await job.abort(timeout=0.2)

    return _document_status_payload(document)


def _get_document(*, db: Session, document_id: UUID, tenant_id: UUID) -> DBDocument:
    document = db.query(DBDocument).filter(DBDocument.id == document_id, DBDocument.tenant_id == tenant_id).first()
    if not document:
        raise HTTPException(status_code=404, detail=DOC_NOT_FOUND_DETAIL)
    return document


def _ensure_retryable_document_state(
    *,
    document: DBDocument,
    force: bool,
) -> tuple[str, str]:
    current_status = str(document.status or "").lower()
    if current_status == "processing" or (
        current_status == "pending" and not is_reprocessable_pending_document(document)
    ):
        raise HTTPException(status_code=409, detail=f"Cannot retry a {current_status} document")
    if current_status == "completed" and not force:
        raise HTTPException(status_code=409, detail="Document is already completed (use force=true to reprocess)")

    raw_path = str(document.file_path or "").strip()
    if not raw_path or raw_path.startswith(MANUAL_FILE_PATH_PREFIX):
        raise HTTPException(status_code=409, detail="Document file is not reprocessable")
    return current_status, raw_path


def _apply_retry_parser_backend_override(
    *,
    document: DBDocument,
    raw_path: str,
    parser_backend: str | None,
) -> None:
    requested_parser_backend = str((parser_backend if parser_backend is not None else "")).strip().lower()
    if not requested_parser_backend:
        return
    filename = str(document.filename or raw_path)
    file_ext = Path(filename).suffix.lower()
    if not file_ext:
        file_type = str(document.file_type or "").strip().lower().lstrip(".")
        file_ext = f".{file_type}" if file_type else ""
    try:
        resolved_parser_backend = parser_factory.resolve_backend(file_ext, requested_parser_backend)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    meta = dict(document.doc_metadata or {})
    meta["parser_backend_requested"] = requested_parser_backend
    meta["parser_backend"] = resolved_parser_backend
    meta["parser_backend_resolved"] = None if resolved_parser_backend == "auto" else resolved_parser_backend
    document.doc_metadata = meta


def _retry_chunk_exists(
    *,
    db: Session,
    tenant_id: UUID,
    document_id: uuid.UUID,
    target_key: str,
) -> bool:
    return bool(
        db.query(DocumentChunk.id)
        .filter(
            DocumentChunk.tenant_id == tenant_id,
            DocumentChunk.document_id == document_id,
            DocumentChunk.doc_metadata["doc_pipeline_key"].astext == target_key,  # type: ignore[attr-defined]
        )
        .limit(1)
        .first()
    )


def _maybe_skip_unchanged_retry(
    *,
    db: Session,
    document: DBDocument,
    document_id: uuid.UUID,
    tenant_id: UUID,
    account_id: str,
    current_status: str,
    force: bool,
    skip_if_unchanged: bool,
) -> DocumentStatus | None:
    if not (skip_if_unchanged and current_status == "completed" and force):
        return None
    meta0 = dict(document.doc_metadata or {})
    file_sha = str(get_content_sha256(meta0) or "").strip().lower()
    ready0 = bool(meta0.get("active_pipeline_ready")) if "active_pipeline_ready" in meta0 else True
    active0 = str(meta0.get("active_pipeline_hash") or meta0.get("pipeline_hash") or "").strip()
    if not (file_sha and ready0 and active0):
        return None
    computed0 = compute_pipeline_hash(meta0)
    if not computed0 or computed0 != active0:
        return None

    target_key = f"{document_id}:{active0}"
    if not _retry_chunk_exists(db=db, tenant_id=tenant_id, document_id=document_id, target_key=target_key):
        return None
    audit_log_event(
        db,
        tenant_id=tenant_id,
        actor_id=account_id,
        action="document.retry.skipped",
        resource_type="document",
        resource_id=str(document_id),
        details={"reason": "unchanged", "pipeline_hash": active0},
    )
    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.warning("Failed to commit unchanged-retry audit: %s", str(exc)[:200])
    return _document_status_payload(document)


def _prepare_retry_metadata(
    *,
    document: DBDocument,
    document_id: uuid.UUID,
    force: bool,
) -> tuple[dict[str, Any], str]:
    meta = dict(document.doc_metadata or {})
    meta.pop("cancel_requested", None)
    meta.pop("task_id", None)
    meta.pop("kg_task_id", None)
    active_pipeline_hash = str(meta.get("active_pipeline_hash") or meta.get("pipeline_hash") or "").strip()
    if "active_pipeline_ready" not in meta:
        meta["active_pipeline_ready"] = bool(str(document.status or "").lower() == "completed")

    pipeline_hash = compute_pipeline_hash(meta)
    meta["pipeline_hash"] = pipeline_hash
    if not active_pipeline_hash:
        active_pipeline_hash = pipeline_hash
        meta["active_pipeline_hash"] = active_pipeline_hash
    sync_pipeline_execution_identity(
        meta,
        content_sha256=get_content_sha256(meta),
        pipeline_hash=pipeline_hash,
        parser_backend_resolved=meta.get("parser_backend_resolved"),
    )

    preserve_existing_versions = bool(meta.get("active_pipeline_ready")) and pipeline_hash != active_pipeline_hash
    retry_cleanup = {
        "version": "1",
        "force": bool(force),
        "pipeline_hash": pipeline_hash,
        "scope": "pipeline" if preserve_existing_versions else "document",
    }
    if preserve_existing_versions:
        retry_cleanup["doc_pipeline_key"] = f"{document_id}:{pipeline_hash}"
    meta["retry_cleanup"] = retry_cleanup
    return meta, pipeline_hash


def _mark_retry_pending(
    *,
    db: Session,
    document: DBDocument,
    meta: dict[str, Any],
    pipeline_hash: str,
) -> None:
    document.doc_metadata = meta
    document.status = "pending"
    document.processing_progress = 0
    document.current_stage = "queued"
    document.failed_stage = None
    document.error_code = None
    document.next_retry_at = None
    document.error_message = None
    db.commit()
    db.refresh(document)
    try:
        reconcile_document_index_channels(
            db,
            document=document,
            pipeline_hash=pipeline_hash,
            reset_enabled_to_pending=True,
            commit=True,
        )
    except Exception as exc:
        logger.warning("Failed to reset document index channel diagnostics: %s", str(exc)[:200])


async def retry_document(
    *,
    document_id: UUID,
    background_tasks: BackgroundTasks,
    force: bool = False,
    skip_if_unchanged: bool = False,
    parser_backend: str | None = None,
    tenant_id: UUID,
    account_id: str,
    db: Session,
) -> DocumentStatus:
    """
    Retry a failed/cancelled document processing task.

    Notes:
    - Existing chunks and indexes are cleaned by the accepted worker before reprocessing.
    - Use `force=true` to allow retrying completed documents.
    """
    dataset_service.ensure_member(db, tenant_id, account_id)
    document = _get_document(
        db=db,
        document_id=document_id,
        tenant_id=tenant_id,
    )
    assert_document_writable_for_lifecycle(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        document=document,
    )

    current_status, raw_path = _ensure_retryable_document_state(
        document=document,
        force=force,
    )
    _apply_retry_parser_backend_override(
        document=document,
        raw_path=raw_path,
        parser_backend=parser_backend,
    )
    unchanged_payload = _maybe_skip_unchanged_retry(
        db=db,
        document=document,
        document_id=document_id,
        tenant_id=tenant_id,
        account_id=account_id,
        current_status=current_status,
        force=force,
        skip_if_unchanged=skip_if_unchanged,
    )
    if unchanged_payload is not None:
        return unchanged_payload

    source = resolve_retry_source(document=document, raw_path=raw_path, tenant_id=tenant_id)
    meta, pipeline_hash = _prepare_retry_metadata(
        document=document,
        document_id=document_id,
        force=force,
    )
    _mark_retry_pending(
        db=db,
        document=document,
        meta=meta,
        pipeline_hash=pipeline_hash,
    )
    await dispatch_retry_document(
        source=source,
        background_tasks=background_tasks,
        document=document,
        db=db,
        tenant_id=tenant_id,
        requested_by=account_id,
        pipeline_hash=pipeline_hash,
    )
    return _document_status_payload(document)

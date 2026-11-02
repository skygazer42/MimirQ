import asyncio
import contextlib
import uuid
from pathlib import Path
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.api.schemas.document import DocumentStatus
from app.api.utils import document_dispatch
from app.core.config import settings
from app.core.database import get_db
from app.models.document import Document as DBDocument
from app.models.document import DocumentChunk
from app.parsing.factory import parser_factory
from app.rag.core.logging import get_logger
from app.services import dataset_service
from app.services.audit_log_service import audit_log_event
from app.services.document_access_service import (
    assert_document_readable_for_lifecycle,
    assert_document_writable_for_lifecycle,
    get_document_for_lifecycle,
)
from app.services.document_identity import compute_pipeline_hash, get_content_sha256, sync_pipeline_execution_identity
from app.services.document_index_channel_service import reconcile_document_index_channels
from app.services.document_lifecycle_service import (
    DOC_NOT_FOUND_DETAIL,
    MANUAL_FILE_PATH_PREFIX,
    _delete_document_lifecycle,
    is_reprocessable_pending_document,
)
from app.storage.object.minio import MinIOService
from app.storage.object.runtime import is_object_storage_uri, resolve_document_object_reference
from app.tasks.queue import enqueue_document_processing, get_queue

_DEFAULT_HTTP_EXCEPTION_RESPONSES = {
    400: {"description": "Bad Request"},
    403: {"description": "Forbidden"},
    404: {"description": "Not Found"},
    409: {"description": "Conflict"},
    416: {"description": "Range Not Satisfiable"},
}

router = APIRouter(responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
logger = get_logger("api.documents")


@router.get("/{document_id}/status", response_model=DocumentStatus, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def get_document_status(
    document_id: UUID,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """
    Get document processing status (for polling).
    """
    dataset_service.ensure_member(db, tenant_id, account_id)
    document = get_document_for_lifecycle(db, tenant_id, document_id)

    if not document:
        raise HTTPException(status_code=404, detail=DOC_NOT_FOUND_DETAIL)

    assert_document_readable_for_lifecycle(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        document=document,
    )

    return _document_status_payload(document)


@router.post("/{document_id}/cancel", response_model=DocumentStatus, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def cancel_document_processing(
    document_id: UUID,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """
    Cancel an in-progress document processing task.

    Notes:
    - When TASK_QUEUE_ENABLED=true, this will best-effort abort the arq job.
    - When queue is disabled, the in-process/background worker cooperatively checks the cancelled status.
    """
    dataset_service.ensure_member(db, tenant_id, account_id)

    document = get_document_for_lifecycle(db, tenant_id, document_id)
    if not document:
        raise HTTPException(status_code=404, detail=DOC_NOT_FOUND_DETAIL)

    assert_document_writable_for_lifecycle(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        document=document,
    )

    current_status = document.status.lower()
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


@router.post("/{document_id}/retry", response_model=DocumentStatus, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def retry_document_processing(
    document_id: UUID,
    background_tasks: BackgroundTasks,
    force: bool = False,
    skip_if_unchanged: bool = False,
    parser_backend: str | None = None,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """
    Retry a failed/cancelled document processing task.

    Notes:
    - Existing chunks and indexes are cleaned by the accepted worker before reprocessing.
    - Use `force=true` to allow retrying completed documents.
    """
    dataset_service.ensure_member(db, tenant_id, account_id)
    document = get_document_for_lifecycle(db, tenant_id, document_id)
    if not document:
        raise HTTPException(status_code=404, detail=DOC_NOT_FOUND_DETAIL)
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

    source = _resolve_retry_source(
        document=document,
        raw_path=raw_path,
        tenant_id=tenant_id,
    )
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
    task_id = await _enqueue_retry_processing(
        db=db,
        document=document,
        document_id=document_id,
        tenant_id=tenant_id,
        account_id=account_id,
        pipeline_hash=pipeline_hash,
    )
    if task_id:
        _persist_retry_task_id(db=db, document=document, task_id=task_id)
    else:
        if settings.TASK_QUEUE_ENABLED:
            logger.error(
                "Document queue returned no task id while retry handoff is required for document %s",
                document_id,
            )
            document_dispatch.raise_document_processing_queue_unavailable(db=db, db_document=document)
        if isinstance(source, Path):
            background_tasks.add_task(
                document_dispatch.run_document_processing_limited,
                source,
                document_id,
                tenant_id,
                meta.get("parser_backend"),
                meta.get("chunk_strategy"),
            )
        else:
            store, object_name = source
            _schedule_retry_from_object_store(
                background_tasks=background_tasks,
                store=store,
                object_name=object_name,
                document=document,
                document_id=document_id,
                tenant_id=tenant_id,
                meta=meta,
            )
    return _document_status_payload(document)


@router.delete("/{document_id}", status_code=204, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def delete_document(
    document_id: UUID,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> None:
    """
    Delete document.
    """
    await _delete_document_lifecycle(
        document_id=document_id,
        tenant_id=tenant_id,
        account_id=account_id,
        db=db,
        enforce_permissions=True,
    )
    return None


def _document_status_payload(document: DBDocument) -> dict[str, Any]:
    return {
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


def _ensure_retryable_document_state(
    *,
    document: DBDocument,
    force: bool,
) -> tuple[str, str]:
    current_status = document.status.lower()
    if current_status == "processing" or (
        current_status == "pending" and not is_reprocessable_pending_document(document)
    ):
        raise HTTPException(status_code=409, detail=f"Cannot retry a {current_status} document")
    if current_status == "completed" and not force:
        raise HTTPException(status_code=409, detail="Document is already completed (use force=true to reprocess)")

    raw_path = document.file_path.strip()
    if not raw_path or raw_path.startswith(MANUAL_FILE_PATH_PREFIX):
        raise HTTPException(status_code=409, detail="Document file is not reprocessable")
    return current_status, raw_path


def _apply_retry_parser_backend_override(
    *,
    document: DBDocument,
    raw_path: str,
    parser_backend: str | None,
) -> None:
    requested_parser_backend = (parser_backend or "").strip().lower()
    if not requested_parser_backend:
        return
    filename = document.filename or raw_path
    file_ext = Path(filename).suffix.lower()
    if not file_ext:
        file_type = document.file_type.strip().lower().lstrip(".")
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
    document_id: UUID,
    target_key: str,
) -> bool:
    try:
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
    except Exception:
        rows = (
            db.query(DocumentChunk.doc_metadata)
            .filter(
                DocumentChunk.tenant_id == tenant_id,
                DocumentChunk.document_id == document_id,
            )
            .limit(200)
            .all()
        )
        for (chunk_meta,) in rows:
            meta = chunk_meta if isinstance(chunk_meta, dict) else {}
            key = str(meta.get("doc_pipeline_key") or "").strip()
            if key == target_key:
                return True
        return False


def _maybe_skip_unchanged_retry(
    *,
    db: Session,
    document: DBDocument,
    document_id: UUID,
    tenant_id: UUID,
    account_id: str,
    current_status: str,
    force: bool,
    skip_if_unchanged: bool,
) -> dict[str, Any] | None:
    if not (skip_if_unchanged and current_status == "completed" and force):
        return None
    metadata = dict(document.doc_metadata or {})
    file_sha = get_content_sha256(metadata)
    active_ready = bool(metadata.get("active_pipeline_ready")) if "active_pipeline_ready" in metadata else True
    active_hash = str(metadata.get("active_pipeline_hash") or metadata.get("pipeline_hash") or "").strip()
    if not (file_sha and active_ready and active_hash):
        return None
    try:
        current_hash = compute_pipeline_hash(metadata)
    except Exception:
        current_hash = ""
    if not current_hash or current_hash != active_hash:
        return None

    target_key = f"{document_id}:{active_hash}"
    if not _retry_chunk_exists(db=db, tenant_id=tenant_id, document_id=document_id, target_key=target_key):
        return None
    audit_log_event(
        db,
        tenant_id=tenant_id,
        actor_id=account_id,
        action="document.retry.skipped",
        resource_type="document",
        resource_id=str(document_id),
        details={"reason": "unchanged", "pipeline_hash": active_hash},
    )
    try:
        db.commit()
    except Exception:
        db.rollback()
    return _document_status_payload(document)


def _resolve_retry_source(
    *,
    document: DBDocument,
    raw_path: str,
    tenant_id: UUID,
) -> Path | tuple[MinIOService, str]:
    if not is_object_storage_uri(raw_path):
        file_path = Path(raw_path)
        if not file_path.exists() or not file_path.is_file():
            raise HTTPException(status_code=404, detail="Document file not found")
        return file_path

    try:
        store, ref = resolve_document_object_reference(
            raw_path,
            tenant_id=tenant_id,
            dataset_id=document.dataset_id,
            document_id=document.id,
            file_type=document.file_type,
            document_metadata=dict(document.doc_metadata or {}),
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="Object storage is disabled") from exc
    except ValueError as exc:
        if str(exc) in {"object_bucket_denied", "object_key_denied"}:
            raise HTTPException(status_code=403, detail="Document file access denied") from exc
        raise HTTPException(status_code=404, detail="Document file not found") from exc

    try:
        store.stat_object(object_name=ref.object_name)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=404, detail="Document file not found") from exc
    return store, ref.object_name


def _prepare_retry_metadata(
    *,
    document: DBDocument,
    document_id: UUID,
    force: bool,
) -> tuple[dict[str, Any], str]:
    meta = dict(document.doc_metadata or {})
    meta.pop("cancel_requested", None)
    meta.pop("task_id", None)
    meta.pop("kg_task_id", None)
    active_pipeline_hash = str(meta.get("active_pipeline_hash") or meta.get("pipeline_hash") or "").strip()
    if "active_pipeline_ready" not in meta:
        meta["active_pipeline_ready"] = document.status.lower() == "completed"

    pipeline_hash = compute_pipeline_hash(meta)
    meta["pipeline_hash"] = pipeline_hash
    if not active_pipeline_hash:
        active_pipeline_hash = pipeline_hash
        meta["active_pipeline_hash"] = active_pipeline_hash
    sync_pipeline_execution_identity(
        meta,
        content_sha256=get_content_sha256(meta),
        pipeline_hash=pipeline_hash,
        parser_backend_resolved=str(meta.get("parser_backend_resolved") or "").strip() or None,
    )

    preserve_existing_versions = bool(meta.get("active_pipeline_ready")) and pipeline_hash != active_pipeline_hash
    retry_cleanup = {
        "version": "1",
        "force": force,
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
    with contextlib.suppress(Exception):
        reconcile_document_index_channels(
            db,
            document=document,
            pipeline_hash=pipeline_hash,
            reset_enabled_to_pending=True,
            commit=True,
        )


async def _enqueue_retry_processing(
    *,
    db: Session,
    document: DBDocument,
    document_id: UUID,
    tenant_id: UUID,
    account_id: str,
    pipeline_hash: str,
) -> str | None:
    try:
        return await enqueue_document_processing(
            tenant_id=tenant_id,
            document_id=document_id,
            requested_by=account_id,
            job_id=f"doc:{tenant_id}:{document_id}:{pipeline_hash}",
        )
    except Exception as exc:  # noqa: BLE001
        if settings.TASK_QUEUE_ENABLED:
            logger.error(
                "Document queue unavailable while retry handoff is required for document %s: %s",
                document_id,
                str(exc)[:200],
            )
            document_dispatch.raise_document_processing_queue_unavailable(db=db, db_document=document, exc=exc)
        raise


def _persist_retry_task_id(*, db: Session, document: DBDocument, task_id: str) -> None:
    meta = dict(document.doc_metadata or {})
    meta["task_id"] = task_id
    document.doc_metadata = meta
    db.commit()
    db.refresh(document)


def _schedule_retry_from_object_store(
    *,
    background_tasks: BackgroundTasks,
    store: MinIOService,
    object_name: str,
    document: DBDocument,
    document_id: UUID,
    tenant_id: UUID,
    meta: dict[str, Any],
) -> None:
    temp_dir = (Path(settings.UPLOAD_DIR) / str(tenant_id) / ".tmp").resolve(strict=False)
    suffix = f".{document.file_type.lower()}"
    temp_path = temp_dir / f"{document_id}.{uuid.uuid4().hex}{suffix}"

    async def _process_from_object_store() -> None:
        try:
            await asyncio.to_thread(
                store.download_object_to_path,
                object_name=object_name,
                destination=temp_path,
                max_bytes=settings.MAX_FILE_SIZE,
            )
            await document_dispatch.run_document_processing_limited(
                file_path=temp_path,
                document_id=document_id,
                tenant_id=tenant_id,
                parser_backend=meta.get("parser_backend"),
                chunk_strategy=meta.get("chunk_strategy"),
                db=None,
            )
        finally:
            with contextlib.suppress(Exception):
                temp_path.unlink(missing_ok=True)

    background_tasks.add_task(_process_from_object_store)

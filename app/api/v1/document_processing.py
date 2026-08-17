import asyncio
import contextlib
import importlib
import uuid
from pathlib import Path
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.api.schemas.document import DocumentStatus
from app.core.database import get_db
from app.models.document import Document as DBDocument
from app.models.document import DocumentChunk

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


def _document_status_payload(document: DBDocument) -> dict:
    return {
        "id": document.id,
        "status": document.status,
        "processing_progress": document.processing_progress,
        "current_stage": document.current_stage,
        "failed_stage": getattr(document, "failed_stage", None),
        "error_code": getattr(document, "error_code", None),
        "processing_attempts": int(getattr(document, "processing_attempts", 0) or 0),
        "next_retry_at": getattr(document, "next_retry_at", None),
        "error_message": document.error_message,
    }


@router.get("/{document_id}/status", response_model=DocumentStatus, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def get_document_status(
    document_id: uuid.UUID,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Get document processing status (for polling).
    """
    documents_module = _documents_module()
    documents_module.DatasetService.ensure_member(db, tenant_id, account_id)
    document = db.query(DBDocument).filter(DBDocument.id == document_id, DBDocument.tenant_id == tenant_id).first()

    if not document:
        raise HTTPException(status_code=404, detail=documents_module.DOC_NOT_FOUND_DETAIL)

    documents_module._assert_document_readable_for_lifecycle(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        document=document,
    )

    return _document_status_payload(document)


@router.post("/{document_id}/cancel", response_model=DocumentStatus, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def cancel_document_processing(
    document_id: uuid.UUID,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Cancel an in-progress document processing task.

    Notes:
    - When TASK_QUEUE_ENABLED=true, this will best-effort abort the arq job.
    - When queue is disabled, the in-process/background worker cooperatively checks the cancelled status.
    """
    documents_module = _documents_module()
    documents_module.DatasetService.ensure_member(db, tenant_id, account_id)

    document = db.query(DBDocument).filter(DBDocument.id == document_id, DBDocument.tenant_id == tenant_id).first()
    if not document:
        raise HTTPException(status_code=404, detail=documents_module.DOC_NOT_FOUND_DETAIL)

    documents_module._assert_document_writable_for_lifecycle(
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

    if bool(getattr(documents_module.settings, "TASK_QUEUE_ENABLED", False)) and task_ids:
        from arq.jobs import Job

        from app.tasks.queue import get_queue

        try:
            queue = await get_queue()
        except Exception as exc:  # noqa: BLE001
            documents_module.logger.warning(
                "Failed to access task queue while aborting tasks %s for document %s: %s",
                task_ids,
                document_id,
                str(exc)[:200],
            )
        else:
            if queue is not None:
                queue_name = getattr(documents_module.settings, "TASK_QUEUE_NAME", "mimirq")
                for task in task_ids:
                    job = Job(task, queue, _queue_name=queue_name)
                    with contextlib.suppress(TimeoutError, asyncio.TimeoutError):
                        await job.abort(timeout=0.2)

    return _document_status_payload(document)


def _get_retry_document(*, documents_module: Any, db: Session, document_id: uuid.UUID, tenant_id: UUID) -> Any:
    document = db.query(DBDocument).filter(DBDocument.id == document_id, DBDocument.tenant_id == tenant_id).first()
    if not document:
        raise HTTPException(status_code=404, detail=documents_module.DOC_NOT_FOUND_DETAIL)
    return document


def _ensure_retryable_document_state(
    *,
    documents_module: Any,
    document: Any,
    force: bool,
) -> tuple[str, str]:
    current_status = str(document.status or "").lower()
    if current_status == "processing" or (
        current_status == "pending" and not documents_module._is_reprocessable_pending_document(document)
    ):
        raise HTTPException(status_code=409, detail=f"Cannot retry a {current_status} document")
    if current_status == "completed" and not force:
        raise HTTPException(status_code=409, detail="Document is already completed (use force=true to reprocess)")

    raw_path = str(document.file_path or "").strip()
    if not raw_path or raw_path.startswith(documents_module.MANUAL_FILE_PATH_PREFIX):
        raise HTTPException(status_code=409, detail="Document file is not reprocessable")
    return current_status, raw_path


def _apply_retry_parser_backend_override(
    *,
    documents_module: Any,
    document: Any,
    raw_path: str,
    parser_backend: str | None,
) -> None:
    requested_parser_backend = str(parser_backend or "").strip().lower()
    if not requested_parser_backend:
        return
    filename = str(getattr(document, "filename", "") or raw_path)
    file_ext = Path(filename).suffix.lower()
    if not file_ext:
        file_type = str(getattr(document, "file_type", "") or "").strip().lower().lstrip(".")
        file_ext = f".{file_type}" if file_type else ""
    try:
        resolved_parser_backend = documents_module.parser_factory.resolve_backend(file_ext, requested_parser_backend)
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
    documents_module: Any,
    db: Session,
    document: Any,
    document_id: uuid.UUID,
    tenant_id: UUID,
    account_id: str,
    current_status: str,
    force: bool,
    skip_if_unchanged: bool,
) -> dict[str, Any] | None:
    if not (skip_if_unchanged and current_status == "completed" and force):
        return None
    meta0 = dict(document.doc_metadata or {})
    file_sha = str(documents_module.get_content_sha256(meta0) or "").strip().lower()
    ready0 = bool(meta0.get("active_pipeline_ready")) if "active_pipeline_ready" in meta0 else True
    active0 = str(meta0.get("active_pipeline_hash") or meta0.get("pipeline_hash") or "").strip()
    if not (file_sha and ready0 and active0):
        return None
    try:
        computed0 = documents_module._compute_pipeline_hash(meta0)
    except Exception:
        computed0 = ""
    if not computed0 or computed0 != active0:
        return None

    target_key = f"{document_id}:{active0}"
    if not _retry_chunk_exists(db=db, tenant_id=tenant_id, document_id=document_id, target_key=target_key):
        return None
    documents_module.audit_log_event(
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
    except Exception:
        db.rollback()
    return _document_status_payload(document)


def _resolve_retry_source(
    *,
    documents_module: Any,
    document: Any,
    raw_path: str,
    tenant_id: UUID,
) -> tuple[Any | None, str | None, Path | None]:
    if not documents_module.is_object_storage_uri(raw_path):
        file_path = Path(raw_path)
        if not file_path.exists() or not file_path.is_file():
            raise HTTPException(status_code=404, detail=documents_module.DOCUMENT_FILE_NOT_FOUND_DETAIL)
        return None, None, file_path

    try:
        store, ref = documents_module.resolve_document_object_reference(
            raw_path,
            tenant_id=tenant_id,
            dataset_id=document.dataset_id,
            document_id=document.id,
            file_type=document.file_type,
            document_metadata=dict(getattr(document, "doc_metadata", None) or {}),
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="Object storage is disabled") from exc
    except ValueError as exc:
        if str(exc) in {"object_bucket_denied", "object_key_denied"}:
            raise HTTPException(status_code=403, detail=documents_module.DOCUMENT_FILE_ACCESS_DENIED_DETAIL) from exc
        raise HTTPException(status_code=404, detail=documents_module.DOCUMENT_FILE_NOT_FOUND_DETAIL) from exc

    try:
        store.stat_object(object_name=ref.object_name)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=404, detail=documents_module.DOCUMENT_FILE_NOT_FOUND_DETAIL) from exc
    return store, ref.object_name, None


def _prepare_retry_metadata(
    *,
    documents_module: Any,
    document: Any,
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

    pipeline_hash = documents_module._compute_pipeline_hash(meta)
    meta["pipeline_hash"] = pipeline_hash
    if not active_pipeline_hash:
        active_pipeline_hash = pipeline_hash
        meta["active_pipeline_hash"] = active_pipeline_hash
    documents_module.sync_pipeline_execution_identity(
        meta,
        content_sha256=documents_module.get_content_sha256(meta),
        pipeline_hash=pipeline_hash,
        parser_backend_resolved=str(meta.get("parser_backend_resolved") or "").strip() or None,
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
    documents_module: Any,
    db: Session,
    document: Any,
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
        documents_module.reconcile_document_index_channels(
            db,
            document=document,
            pipeline_hash=pipeline_hash,
            reset_enabled_to_pending=True,
            commit=True,
        )


async def _enqueue_retry_processing(
    *,
    documents_module: Any,
    db: Session,
    document: Any,
    document_id: uuid.UUID,
    tenant_id: UUID,
    account_id: str,
    pipeline_hash: str,
) -> str | None:
    try:
        return await documents_module.enqueue_document_processing(
            tenant_id=tenant_id,
            document_id=document_id,
            requested_by=account_id,
            job_id=f"doc:{tenant_id}:{document_id}:{pipeline_hash}",
        )
    except Exception as exc:  # noqa: BLE001
        if documents_module._task_queue_required():
            documents_module.logger.error(
                "Document queue unavailable while retry handoff is required for document %s: %s",
                document_id,
                str(exc)[:200],
            )
            documents_module._raise_document_processing_queue_unavailable(db=db, db_document=document, exc=exc)
        raise


def _persist_retry_task_id(*, db: Session, document: Any, task_id: str) -> None:
    meta = dict(document.doc_metadata or {})
    meta["task_id"] = task_id
    document.doc_metadata = meta
    db.commit()
    db.refresh(document)


def _schedule_retry_from_object_store(
    *,
    background_tasks: BackgroundTasks,
    documents_module: Any,
    store: Any,
    object_name: str,
    document: Any,
    document_id: uuid.UUID,
    tenant_id: UUID,
    meta: dict[str, Any],
) -> None:
    temp_dir = (Path(documents_module.settings.UPLOAD_DIR) / str(tenant_id) / ".tmp").resolve(strict=False)
    suffix = f".{(document.file_type or '').lower()}"
    temp_path = temp_dir / f"{document_id}.{uuid.uuid4().hex}{suffix}"

    async def _process_from_object_store() -> None:
        try:
            await asyncio.to_thread(
                store.download_object_to_path,
                object_name=str(object_name),
                destination=temp_path,
                max_bytes=int(getattr(documents_module.settings, "MAX_FILE_SIZE", 0) or 0),
            )
            await documents_module.run_document_processing_limited(
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


def _schedule_retry_processing(
    *,
    background_tasks: BackgroundTasks,
    documents_module: Any,
    db: Session,
    document: Any,
    document_id: uuid.UUID,
    tenant_id: UUID,
    meta: dict[str, Any],
    file_path: Path | None,
    store: Any | None,
    object_name: str | None,
) -> None:
    if documents_module._task_queue_required():
        documents_module.logger.error(
            "Document queue returned no task id while retry handoff is required for document %s",
            document_id,
        )
        documents_module._raise_document_processing_queue_unavailable(db=db, db_document=document)
    if file_path is not None:
        background_tasks.add_task(
            documents_module.run_document_processing_limited,
            file_path,
            document_id,
            tenant_id,
            meta.get("parser_backend"),
            meta.get("chunk_strategy"),
        )
        return
    _schedule_retry_from_object_store(
        background_tasks=background_tasks,
        documents_module=documents_module,
        store=store,
        object_name=str(object_name),
        document=document,
        document_id=document_id,
        tenant_id=tenant_id,
        meta=meta,
    )


@router.post("/{document_id}/retry", response_model=DocumentStatus, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def retry_document_processing(
    document_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    force: bool = False,
    skip_if_unchanged: bool = False,
    parser_backend: str | None = None,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Retry a failed/cancelled document processing task.

    Notes:
    - Existing chunks and indexes are cleaned by the accepted worker before reprocessing.
    - Use `force=true` to allow retrying completed documents.
    """
    documents_module = _documents_module()
    documents_module.DatasetService.ensure_member(db, tenant_id, account_id)
    document = _get_retry_document(
        documents_module=documents_module,
        db=db,
        document_id=document_id,
        tenant_id=tenant_id,
    )
    documents_module._assert_document_writable_for_lifecycle(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        document=document,
    )

    current_status, raw_path = _ensure_retryable_document_state(
        documents_module=documents_module,
        document=document,
        force=force,
    )
    _apply_retry_parser_backend_override(
        documents_module=documents_module,
        document=document,
        raw_path=raw_path,
        parser_backend=parser_backend,
    )
    unchanged_payload = _maybe_skip_unchanged_retry(
        documents_module=documents_module,
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

    store, object_name, file_path = _resolve_retry_source(
        documents_module=documents_module,
        document=document,
        raw_path=raw_path,
        tenant_id=tenant_id,
    )
    meta, pipeline_hash = _prepare_retry_metadata(
        documents_module=documents_module,
        document=document,
        document_id=document_id,
        force=force,
    )
    _mark_retry_pending(
        documents_module=documents_module,
        db=db,
        document=document,
        meta=meta,
        pipeline_hash=pipeline_hash,
    )
    task_id = await _enqueue_retry_processing(
        documents_module=documents_module,
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
        _schedule_retry_processing(
            background_tasks=background_tasks,
            documents_module=documents_module,
            db=db,
            document=document,
            document_id=document_id,
            tenant_id=tenant_id,
            meta=meta,
            file_path=file_path,
            store=store,
            object_name=object_name,
        )
    return _document_status_payload(document)


@router.delete("/{document_id}", status_code=204, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def delete_document(
    document_id: uuid.UUID,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Delete document.
    """
    documents_module = _documents_module()
    await documents_module._delete_document_lifecycle(
        document_id=document_id,
        tenant_id=tenant_id,
        account_id=account_id,
        db=db,
        enforce_permissions=True,
    )
    return None

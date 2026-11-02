"""API-side document scheduling and local processing lifecycle."""

import asyncio
import contextlib
from pathlib import Path
from typing import Any, NoReturn
from uuid import UUID

from fastapi import BackgroundTasks, HTTPException
from sqlalchemy.orm import Session

from app.core.async_bridge import run_coroutine_in_thread
from app.core.config import settings
from app.models.document import Document as DBDocument
from app.parsing.processors.processor import document_processor
from app.rag.core.logging import get_logger
from app.storage.object.runtime import is_object_storage_uri
from app.tasks.queue import enqueue_document_processing

logger = get_logger("api.documents")

DOCUMENT_PROCESSING_QUEUE_UNAVAILABLE_DETAIL = "Document processing queue unavailable"


_background_processing_semaphores: dict[int, tuple[int, asyncio.Semaphore]] = {}


async def schedule_document_processing(
    *,
    db: Session,
    background_tasks: BackgroundTasks | None,
    tenant_id: UUID,
    document_id: UUID,
    file_path: Path,
    requested_by: str,
    pipeline_hash: str,
    parser_backend: str,
    chunk_strategy: str,
    db_document: DBDocument,
) -> bool:
    job_id = f"doc:{tenant_id}:{document_id}:{pipeline_hash}"
    object_backed = is_object_storage_uri(db_document.file_path)
    queue_required = settings.TASK_QUEUE_ENABLED
    task_id = None
    try:
        task_id = await enqueue_document_processing(
            tenant_id=tenant_id,
            document_id=document_id,
            requested_by=requested_by,
            job_id=job_id,
        )
    except Exception as exc:  # noqa: BLE001
        if queue_required:
            logger.error("Document queue unavailable while handoff is required: %s", str(exc)[:200])
            raise_document_processing_queue_unavailable(db=db, db_document=db_document, exc=exc)
        logger.warning("Document queue unavailable; using local processing fallback: %s", str(exc)[:200])
    if task_id:
        try:
            meta = dict(db_document.doc_metadata or {})
            meta["task_id"] = task_id
            db_document.doc_metadata = meta
            db.commit()
            db.refresh(db_document)
        except Exception as exc:  # noqa: BLE001
            with contextlib.suppress(Exception):
                db.rollback()
            logger.warning("Document task queued but task metadata refresh failed: %s", str(exc)[:200])
        return not object_backed

    if queue_required:
        logger.error("Document queue returned no task id while handoff is required")
        raise_document_processing_queue_unavailable(db=db, db_document=db_document)

    if background_tasks is not None:
        try:
            if object_backed:
                background_tasks.add_task(
                    _run_document_processing_with_cleanup,
                    file_path,
                    document_id,
                    tenant_id,
                    parser_backend,
                    chunk_strategy,
                )
            else:
                background_tasks.add_task(
                    run_document_processing_limited,
                    file_path,
                    document_id,
                    tenant_id,
                    parser_backend,
                    chunk_strategy,
                )
        except Exception as exc:
            _mark_document_processing_schedule_failed(db=db, db_document=db_document)
            logger.error("Failed to register document background task: %s", str(exc)[:200])
            raise
        return True

    await run_document_processing_limited(
        file_path,
        document_id,
        tenant_id,
        parser_backend,
        chunk_strategy,
    )
    return not object_backed


async def run_document_processing_limited(*args: Any, **kwargs: Any) -> Any:
    sem = _get_background_processing_semaphore()
    async with sem:
        return await run_coroutine_in_thread(
            lambda: document_processor.process_document(*args, **kwargs),
            on_cancelled_worker_error=_log_cancelled_background_processing_error,
        )


def raise_document_processing_queue_unavailable(
    *,
    db: Session,
    db_document: DBDocument,
    exc: Exception | None = None,
) -> NoReturn:
    _mark_document_processing_schedule_failed(db=db, db_document=db_document)
    if exc is not None:
        raise HTTPException(status_code=503, detail=DOCUMENT_PROCESSING_QUEUE_UNAVAILABLE_DETAIL) from exc
    raise HTTPException(status_code=503, detail=DOCUMENT_PROCESSING_QUEUE_UNAVAILABLE_DETAIL)


def _mark_document_processing_schedule_failed(*, db: Session, db_document: DBDocument) -> None:
    meta = dict(db_document.doc_metadata or {})
    meta.pop("task_id", None)
    meta.pop("kg_task_id", None)
    db_document.doc_metadata = meta
    db_document.status = "failed"
    db_document.current_stage = "failed"
    db_document.error_message = "document_processing_schedule_failed"
    try:
        db.commit()
    except Exception as exc:  # noqa: BLE001
        with contextlib.suppress(Exception):
            db.rollback()
        logger.error("Failed to mark unscheduled document as failed: %s", str(exc)[:200])


def _get_background_processing_semaphore() -> asyncio.Semaphore:
    limit = max(1, settings.API_DOCUMENT_BACKGROUND_MAX_CONCURRENCY or 2)
    loop_id = id(asyncio.get_running_loop())
    cached = _background_processing_semaphores.get(loop_id)
    if cached is None or cached[0] != limit:
        sem = asyncio.Semaphore(limit)
        _background_processing_semaphores[loop_id] = (limit, sem)
        return sem
    return cached[1]


def _log_cancelled_background_processing_error(exc: BaseException) -> None:
    logger.warning(
        "Background document processing failed after request cancellation",
        exc_info=(type(exc), exc, exc.__traceback__),
    )


async def _run_document_processing_with_cleanup(
    file_path: Path,
    document_id: UUID,
    tenant_id: UUID,
    parser_backend: str,
    chunk_strategy: str,
) -> None:
    try:
        await run_document_processing_limited(
            file_path,
            document_id,
            tenant_id,
            parser_backend,
            chunk_strategy,
        )
    finally:
        with contextlib.suppress(OSError):
            file_path.unlink(missing_ok=True)

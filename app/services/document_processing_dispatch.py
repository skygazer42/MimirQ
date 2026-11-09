"""Document queue handoff and local worker resource ownership."""

import asyncio
import contextlib
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn
from uuid import UUID

from fastapi import BackgroundTasks, HTTPException
from minio.error import S3Error
from sqlalchemy.orm import Session

from app.core.async_bridge import run_blocking_in_thread, run_coroutine_in_thread
from app.core.config import settings
from app.models.document import Document as DBDocument
from app.parsing.processors.processor import document_processor
from app.rag.core.logging import get_logger
from app.storage.object.minio import MinIOService
from app.storage.object.runtime import is_object_storage_uri, resolve_document_object_reference
from app.tasks.queue import enqueue_document_processing

logger = get_logger("services.document_processing_dispatch")
DOCUMENT_PROCESSING_QUEUE_UNAVAILABLE_DETAIL = "Document processing queue unavailable"
DOCUMENT_FILE_ACCESS_DENIED_DETAIL = "Document file access denied"
DOCUMENT_FILE_NOT_FOUND_DETAIL = "Document file not found"
_background_processing_semaphores: dict[int, tuple[int, asyncio.Semaphore]] = {}


@dataclass(frozen=True)
class LocalProcessingSource:
    path: Path


@dataclass(frozen=True)
class StoredProcessingSource:
    """A validated reference, retained until a local download is actually needed."""

    uri: str
    store: MinIOService
    object_name: str


def resolve_retry_source(
    *, document: DBDocument, raw_path: str, tenant_id: UUID
) -> LocalProcessingSource | StoredProcessingSource:
    if not is_object_storage_uri(raw_path):
        file_path = Path(raw_path)
        if not file_path.is_file():
            raise HTTPException(status_code=404, detail=DOCUMENT_FILE_NOT_FOUND_DETAIL)
        return LocalProcessingSource(file_path)
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
            raise HTTPException(status_code=403, detail=DOCUMENT_FILE_ACCESS_DENIED_DETAIL) from exc
        raise HTTPException(status_code=404, detail=DOCUMENT_FILE_NOT_FOUND_DETAIL) from exc
    try:
        store.stat_object(object_name=ref.object_name)
    except S3Error as exc:
        if exc.code != "NoSuchKey":
            raise
        raise HTTPException(status_code=404, detail=DOCUMENT_FILE_NOT_FOUND_DETAIL) from exc
    return StoredProcessingSource(raw_path, store, ref.object_name)


def _get_background_processing_semaphore() -> asyncio.Semaphore:
    limit = max(1, settings.API_DOCUMENT_BACKGROUND_MAX_CONCURRENCY or 2)
    loop_id = id(asyncio.get_running_loop())
    cached = _background_processing_semaphores.get(loop_id)
    if cached is None or cached[0] != limit:
        semaphore = asyncio.Semaphore(limit)
        _background_processing_semaphores[loop_id] = (limit, semaphore)
        return semaphore
    return cached[1]


def _log_cancelled_background_processing_error(exc: BaseException) -> None:
    logger.warning(
        "Background document processing failed after request cancellation", exc_info=(type(exc), exc, exc.__traceback__)
    )


async def run_document_processing_limited(
    file_path: Path,
    document_id: UUID,
    tenant_id: UUID,
    parser_backend: str | None = None,
    chunk_strategy: str | None = None,
) -> dict[str, Any]:
    # The private worker loop creates its own DB session. The permit and source
    # remain owned until the worker finishes, including repeated cancellation.
    async with _get_background_processing_semaphore():
        return await run_coroutine_in_thread(
            lambda: document_processor.process_document(
                file_path, document_id, tenant_id, parser_backend, chunk_strategy
            ),
            on_cancelled_worker_error=_log_cancelled_background_processing_error,
        )


def mark_document_processing_schedule_failed(*, db: Session, document: DBDocument) -> None:
    meta = dict(document.doc_metadata or {})
    meta.pop("task_id", None)
    meta.pop("kg_task_id", None)
    document.doc_metadata = meta
    document.status = "failed"
    document.current_stage = "failed"
    document.error_message = "document_processing_schedule_failed"
    try:
        db.commit()
    except Exception as exc:
        with contextlib.suppress(Exception):
            db.rollback()
        logger.error("Failed to mark unscheduled document as failed: %s", str(exc)[:200])


def _raise_queue_unavailable(*, db: Session, document: DBDocument, exc: Exception | None = None) -> NoReturn:
    mark_document_processing_schedule_failed(db=db, document=document)
    if exc is not None:
        raise HTTPException(status_code=503, detail=DOCUMENT_PROCESSING_QUEUE_UNAVAILABLE_DETAIL) from exc
    raise HTTPException(status_code=503, detail=DOCUMENT_PROCESSING_QUEUE_UNAVAILABLE_DETAIL)


async def _enqueue(*, tenant_id: UUID, document: DBDocument, requested_by: str, pipeline_hash: str) -> str | None:
    return await enqueue_document_processing(
        tenant_id=tenant_id,
        document_id=document.id,
        requested_by=requested_by,
        job_id=f"doc:{tenant_id}:{document.id}:{pipeline_hash}",
    )


def _persist_task_id(*, db: Session, document: DBDocument, task_id: str) -> None:
    meta = dict(document.doc_metadata or {})
    meta["task_id"] = task_id
    document.doc_metadata = meta
    db.commit()
    db.refresh(document)


async def _run_uploaded_object_with_cleanup(
    file_path: Path, document_id: UUID, tenant_id: UUID, parser_backend: str | None, chunk_strategy: str | None
) -> None:
    try:
        await run_document_processing_limited(file_path, document_id, tenant_id, parser_backend, chunk_strategy)
    finally:
        with contextlib.suppress(OSError):
            file_path.unlink(missing_ok=True)


async def dispatch_uploaded_document(
    *,
    source: LocalProcessingSource,
    background_tasks: BackgroundTasks | None,
    document: DBDocument,
    db: Session,
    tenant_id: UUID,
    requested_by: str,
    pipeline_hash: str,
    parser_backend: str,
    chunk_strategy: str,
) -> bool:
    """Return whether the accepted local worker owns the request's source file."""
    object_backed = is_object_storage_uri(document.file_path)
    queue_required = settings.TASK_QUEUE_ENABLED
    task_id = None
    try:
        task_id = await _enqueue(
            tenant_id=tenant_id, document=document, requested_by=requested_by, pipeline_hash=pipeline_hash
        )
    except Exception as exc:
        if queue_required:
            logger.error("Document queue unavailable while handoff is required: %s", str(exc)[:200])
            _raise_queue_unavailable(db=db, document=document, exc=exc)
        logger.warning("Document queue unavailable; using local processing fallback: %s", str(exc)[:200])
    if task_id:
        # Acceptance is authoritative even if recording its diagnostic task id
        # fails: do not enqueue a second job or delete a local worker's source.
        try:
            _persist_task_id(db=db, document=document, task_id=task_id)
        except Exception as exc:
            with contextlib.suppress(Exception):
                db.rollback()
            logger.warning("Document task queued but task metadata refresh failed: %s", str(exc)[:200])
        return not object_backed
    if queue_required:
        logger.error("Document queue returned no task id while handoff is required")
        _raise_queue_unavailable(db=db, document=document)
    if background_tasks is not None:
        try:
            background_tasks.add_task(
                _run_uploaded_object_with_cleanup if object_backed else run_document_processing_limited,
                source.path,
                document.id,
                tenant_id,
                parser_backend,
                chunk_strategy,
            )
        except Exception as exc:
            mark_document_processing_schedule_failed(db=db, document=document)
            logger.error("Failed to register document background task: %s", str(exc)[:200])
            raise
        return True
    await run_document_processing_limited(source.path, document.id, tenant_id, parser_backend, chunk_strategy)
    return not object_backed


async def _process_stored_retry(
    *,
    source: StoredProcessingSource,
    temp_path: Path,
    document_id: UUID,
    tenant_id: UUID,
    parser_backend: str | None,
    chunk_strategy: str | None,
) -> None:
    try:
        await run_blocking_in_thread(
            source.store.download_object_to_path,
            object_name=source.object_name,
            destination=temp_path,
            max_bytes=settings.MAX_FILE_SIZE,
        )
        await run_document_processing_limited(
            file_path=temp_path,
            document_id=document_id,
            tenant_id=tenant_id,
            parser_backend=parser_backend,
            chunk_strategy=chunk_strategy,
        )
    finally:
        with contextlib.suppress(OSError):
            temp_path.unlink(missing_ok=True)


async def dispatch_retry_document(
    *,
    source: LocalProcessingSource | StoredProcessingSource,
    background_tasks: BackgroundTasks,
    document: DBDocument,
    db: Session,
    tenant_id: UUID,
    requested_by: str,
    pipeline_hash: str,
) -> None:
    try:
        task_id = await _enqueue(
            tenant_id=tenant_id, document=document, requested_by=requested_by, pipeline_hash=pipeline_hash
        )
    except Exception as exc:
        if settings.TASK_QUEUE_ENABLED:
            logger.error(
                "Document queue unavailable while retry handoff is required for document %s: %s",
                document.id,
                str(exc)[:200],
            )
            _raise_queue_unavailable(db=db, document=document, exc=exc)
        raise
    if task_id:
        _persist_task_id(db=db, document=document, task_id=task_id)
        return
    if settings.TASK_QUEUE_ENABLED:
        logger.error("Document queue returned no task id while retry handoff is required for document %s", document.id)
        _raise_queue_unavailable(db=db, document=document)
    meta = document.doc_metadata or {}
    if isinstance(source, LocalProcessingSource):
        background_tasks.add_task(
            run_document_processing_limited,
            source.path,
            document.id,
            tenant_id,
            meta.get("parser_backend"),
            meta.get("chunk_strategy"),
        )
        return
    temp_dir = (Path(settings.UPLOAD_DIR) / str(tenant_id) / ".tmp").resolve(strict=False)
    temp_path = temp_dir / f"{document.id}.{uuid.uuid4().hex}.{(document.file_type).lower()}"
    background_tasks.add_task(
        _process_stored_retry,
        source=source,
        temp_path=temp_path,
        document_id=document.id,
        tenant_id=tenant_id,
        parser_backend=meta.get("parser_backend"),
        chunk_strategy=meta.get("chunk_strategy"),
    )

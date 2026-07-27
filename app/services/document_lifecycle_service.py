
import asyncio
import contextlib
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.async_bridge import run_blocking_in_thread
from app.core.config import settings
from app.core.database import SessionLocal
from app.models.document import Document as DBDocument
from app.models.document import DocumentChunk
from app.rag.core.logging import get_logger
from app.services.audit_log_service import audit_log_event
from app.services.dataset_service import DatasetService
from app.storage.object.minio import minio_service
from app.storage.object.runtime import is_object_storage_uri, resolve_document_object_reference

logger = get_logger("services.document_lifecycle")

DOC_NOT_FOUND_DETAIL = "Document not found"
MANUAL_FILE_PATH_PREFIX = "manual://"
DELETION_STATE_KEY = "deletion"
DELETION_STATE_DELETING = "deleting"
_SAFE_OBJECT_REFERENCE_ERRORS = frozenset({"invalid_object_storage_uri", "invalid_object_storage_uri_scheme"})
_MISSING_OBJECT_DELETE_MARKERS = (
    "nosuchkey",
    "no such key",
    "nosuchobject",
    "no such object",
    "object does not exist",
    "key does not exist",
)
_CHUNK_METADATA_SCAN_BATCH_SIZE = 256
_DELETE_IO_BATCH_SIZE = 16
_MINIO_DELETE_OBJECT_BATCH_SIZE = 1000
Indexer: Any | None = None


def _get_indexer_class() -> Any:
    global Indexer
    if Indexer is None:
        from app.services.indexer import Indexer as indexer_cls

        Indexer = indexer_cls
    return Indexer


def _get_document_for_delete(db: Session, *, tenant_id: UUID, document_id: UUID) -> DBDocument:
    document = (
        db.query(DBDocument)
        .filter(
            DBDocument.id == document_id,
            DBDocument.tenant_id == tenant_id,
        )
        .first()
    )
    if not document:
        raise HTTPException(status_code=404, detail=DOC_NOT_FOUND_DETAIL)
    return document


def _assert_document_delete_permission(
    db: Session,
    *,
    tenant_id: UUID,
    account_id: str,
    document: DBDocument,
    enforce_permissions: bool,
) -> None:
    if enforce_permissions and document.dataset_id:
        ds = DatasetService.get_dataset(db, tenant_id, document.dataset_id)
        DatasetService.assert_dataset_writable(db, ds, account_id)


def _cancel_processing_document(db: Session, document: DBDocument) -> None:
    if str(document.status or "").lower() not in {"pending", "processing"}:
        return
    doc_meta = dict(document.doc_metadata or {})
    doc_meta["cancel_requested"] = True
    document.doc_metadata = doc_meta
    document.status = "cancelled"
    document.processing_progress = 0
    document.current_stage = "cancelled"
    document.error_message = "cancelled"
    db.commit()
    db.refresh(document)


def _document_task_ids(document: DBDocument) -> list[str]:
    doc_meta = document.doc_metadata or {}
    task_ids: list[str] = []
    for key in ("task_id", "kg_task_id"):
        value = doc_meta.get(key) if isinstance(doc_meta, dict) else None
        if isinstance(value, str) and value.strip():
            task_ids.append(value.strip())
    return task_ids


async def _abort_document_tasks_before_delete(*, document_id: UUID, task_ids: list[str]) -> None:
    if not bool(getattr(settings, "TASK_QUEUE_ENABLED", False)) or not task_ids:
        return
    try:
        from arq.jobs import Job

        from app.tasks.queue import get_queue

        q = await get_queue()
        if q is None:
            return
        queue_name = getattr(settings, "TASK_QUEUE_NAME", "mimirq")
        for task_id in task_ids:
            job = Job(task_id, q, _queue_name=queue_name)
            with contextlib.suppress(TimeoutError, asyncio.TimeoutError):
                await job.abort(timeout=0.2)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Failed to abort document tasks before delete: doc=%s tasks=%s err=%s",
            document_id,
            task_ids,
            str(exc)[:200],
        )


def _add_document_metadata_img_ids(img_ids: set[str], document: DBDocument) -> None:
    doc_meta = document.doc_metadata or {}
    doc_img_ids = doc_meta.get("img_ids") if isinstance(doc_meta, dict) else None
    if not isinstance(doc_img_ids, list):
        return
    for value in doc_img_ids:
        if isinstance(value, str) and value.strip():
            img_ids.add(value)


def _iter_query_rows(query: Any, *, batch_size: int) -> Iterable[Any]:
    if hasattr(query, "yield_per"):
        query = query.yield_per(batch_size)
    if hasattr(query, "__iter__"):
        return query
    if hasattr(query, "all"):
        return query.all()
    return ()


def _row_named_value(row: Any, key: str) -> Any:
    mapping = getattr(row, "_mapping", None)
    if mapping is not None and key in mapping:
        return mapping[key]
    if isinstance(row, dict):
        return row.get(key)
    if hasattr(row, key):
        return getattr(row, key)
    if isinstance(row, (tuple, list)):
        return row[0] if row else None
    try:
        return row[0]
    except (IndexError, KeyError, TypeError):
        return row


def _add_chunk_metadata_img_ids(db: Session, *, tenant_id: UUID, document_id: UUID, img_ids: set[str]) -> None:
    img_id_column = DocumentChunk.doc_metadata["img_id"].astext.label("img_id")
    chunks = (
        db.query(img_id_column)
        .filter(DocumentChunk.document_id == document_id, DocumentChunk.tenant_id == tenant_id)
    )
    for chunk in _iter_query_rows(chunks, batch_size=_CHUNK_METADATA_SCAN_BATCH_SIZE):
        img_id = _row_named_value(chunk, "img_id")
        if isinstance(img_id, str) and img_id.strip():
            img_ids.add(img_id)


def _run_bounded_cleanup_batch(
    values: Iterable[str],
    delete_fn: Callable[[str], None],
    *,
    max_workers: int,
) -> None:
    items = list(values)
    if not items:
        return
    workers = max(1, min(int(max_workers or 1), len(items)))
    if workers == 1:
        for value in items:
            delete_fn(value)
        return
    for start in range(0, len(items), workers):
        batch = items[start : start + workers]
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(delete_fn, value) for value in batch]
            failures: list[BaseException] = []
            for future in futures:
                try:
                    future.result()
                except BaseException as exc:  # noqa: BLE001
                    failures.append(exc)
            if failures:
                raise RuntimeError(f"Cleanup batch failed for {len(failures)} item(s)") from failures[0]


def _delete_document_minio_images(db: Session, *, tenant_id: UUID, document_id: UUID, document: DBDocument) -> None:
    if not settings.MINIO_ENABLED:
        return
    img_ids: set[str] = set()
    _add_document_metadata_img_ids(img_ids, document)
    _add_chunk_metadata_img_ids(db, tenant_id=tenant_id, document_id=document_id, img_ids=img_ids)
    minio_service.delete_images(sorted(img_ids), extension="jpg", batch_size=_MINIO_DELETE_OBJECT_BATCH_SIZE)


def _delete_document_table_store(*, tenant_id: UUID, document_id: UUID, document: DBDocument) -> None:
    if document.dataset_id is None or str(document.file_type or "").lower() not in {"csv", "xls", "xlsx"}:
        return
    from app.services.table_store import table_store_path

    db_path = table_store_path(tenant_id=tenant_id, dataset_id=document.dataset_id, document_id=document.id)
    if db_path.exists():
        db_path.unlink(missing_ok=True)
    with contextlib.suppress(OSError):
        db_path.parent.rmdir()
    with contextlib.suppress(OSError):
        db_path.parent.parent.rmdir()


def _delete_minio_document_object(*, raw_path: str, tenant_id: UUID, document: DBDocument) -> None:
    try:
        store, ref = resolve_document_object_reference(
            raw_path,
            tenant_id=tenant_id,
            dataset_id=document.dataset_id,
            document_id=document.id,
            file_type=document.file_type,
            document_metadata=dict(getattr(document, "doc_metadata", None) or {}),
        )
    except ValueError as exc:
        if str(exc).strip().lower() not in _SAFE_OBJECT_REFERENCE_ERRORS:
            raise
        logger.warning("Skipping malformed object storage document URI: %r", raw_path[:200])
        return
    try:
        store.delete_object(object_name=ref.object_name)
    except RuntimeError as exc:
        message = str(exc).strip().lower()
        if any(marker in message for marker in _MISSING_OBJECT_DELETE_MARKERS) and "bucket" not in message:
            logger.info("Object already absent during document delete: %s", ref.object_name)
            return
        raise


def _delete_local_document_file(*, raw_path: str, tenant_id: UUID) -> None:
    file_path = Path(raw_path)
    if not file_path.exists() or not file_path.is_file():
        return

    from app.services.path_safety import resolve_under_base

    tenant_root = Path(settings.UPLOAD_DIR) / str(tenant_id)
    safe = resolve_under_base(file_path, base=tenant_root)
    if safe is None:
        logger.warning("Skipping unsafe document file delete: %s", raw_path)
        return
    safe.unlink(missing_ok=True)


def _delete_document_file(*, tenant_id: UUID, document: DBDocument) -> None:
    raw_path = str(document.file_path or "").strip()
    if not raw_path or raw_path.startswith(MANUAL_FILE_PATH_PREFIX):
        return
    if is_object_storage_uri(raw_path):
        _delete_minio_document_object(raw_path=raw_path, tenant_id=tenant_id, document=document)
        return
    _delete_local_document_file(raw_path=raw_path, tenant_id=tenant_id)


def _touch_dataset_updated_after_delete(db: Session, *, tenant_id: UUID, document: DBDocument) -> None:
    if getattr(document, "dataset_id", None) is None:
        return
    try:
        from app.models.dataset import Dataset as DBDataset  # noqa: WPS433

        ds = (
            db.query(DBDataset)
            .filter(
                DBDataset.tenant_id == tenant_id,
                DBDataset.id == document.dataset_id,
            )
            .first()
        )
        if ds is not None:
            ds.updated_at = datetime.now(UTC)
    except Exception as exc:  # noqa: BLE001
        logger.debug("Failed touching dataset.updated_at after delete: %s", str(exc)[:200])


def _persist_document_deleting_state(
    db: Session,
    *,
    document: DBDocument,
    account_id: str,
) -> None:
    now_iso = datetime.now(UTC).isoformat()
    doc_meta = dict(document.doc_metadata or {})
    deletion_meta_raw = doc_meta.get(DELETION_STATE_KEY)
    deletion_meta = dict(deletion_meta_raw) if isinstance(deletion_meta_raw, dict) else {}
    deletion_meta["state"] = DELETION_STATE_DELETING
    deletion_meta["requested_at"] = str(deletion_meta.get("requested_at") or now_iso)
    deletion_meta["requested_by"] = str(account_id)
    deletion_meta["updated_at"] = now_iso
    doc_meta[DELETION_STATE_KEY] = deletion_meta
    document.doc_metadata = doc_meta
    document.status = DELETION_STATE_DELETING
    document.current_stage = DELETION_STATE_DELETING
    db.commit()
    db.refresh(document)


def _delete_document_record(
    db: Session,
    *,
    tenant_id: UUID,
    account_id: str,
    document_id: UUID,
    document: DBDocument,
) -> None:
    db.delete(document)
    audit_log_event(
        db,
        tenant_id=tenant_id,
        actor_id=account_id,
        action="document.delete",
        resource_type="document",
        resource_id=str(document_id),
        details={
            "dataset_id": str(document.dataset_id) if getattr(document, "dataset_id", None) else None,
            "file_type": str(getattr(document, "file_type", "") or ""),
            "file_size": int(getattr(document, "file_size", 0) or 0),
        },
    )
    db.commit()


def _cleanup_document_kg_artifacts(db: Session, *, tenant_id: UUID, document_id: UUID) -> None:
    from app.rag.kg.models import KgRelation

    db.query(KgRelation).filter(
        KgRelation.tenant_id == tenant_id,
        KgRelation.document_id == document_id,
    ).delete(synchronize_session=False)
    _get_indexer_class()(db).delete_event_indexes(
        tenant_id=tenant_id,
        document_id=document_id,
        commit=False,
        prune_orphan_entities=True,
        strict=True,
    )


def _log_cancelled_document_delete_error(exc: BaseException) -> None:
    logger.warning(
        "Document delete step failed while its caller was being cancelled",
        exc_info=(type(exc), exc, exc.__traceback__),
    )


async def _run_delete_step_without_blocking_event_loop(func: Any, *args: Any, **kwargs: Any) -> Any:
    return await run_blocking_in_thread(
        func,
        *args,
        on_cancelled_worker_error=_log_cancelled_document_delete_error,
        **kwargs,
    )


def _run_document_delete_session_step(
    session_factory: Callable[[], Session],
    step: Any,
    kwargs: dict[str, Any],
) -> Any:
    worker_db = session_factory()
    try:
        return step(db=worker_db, **kwargs)
    finally:
        with contextlib.suppress(Exception):
            worker_db.close()


def _prepare_document_delete(
    *,
    document_id: UUID,
    tenant_id: UUID,
    account_id: str,
    db: Session,
    enforce_permissions: bool,
    enforce_membership: bool,
) -> list[str]:
    if enforce_membership:
        DatasetService.ensure_member(db, tenant_id, account_id)
    document = _get_document_for_delete(db, tenant_id=tenant_id, document_id=document_id)
    _assert_document_delete_permission(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        document=document,
        enforce_permissions=enforce_permissions,
    )
    _cancel_processing_document(db, document)
    _persist_document_deleting_state(db, document=document, account_id=account_id)
    return _document_task_ids(document)


def _cleanup_document_after_tombstone(
    *,
    document_id: UUID,
    tenant_id: UUID,
    account_id: str,
    db: Session,
) -> None:
    document = _get_document_for_delete(db, tenant_id=tenant_id, document_id=document_id)
    try:
        # The committed `deleting` row is the retryable tombstone. External deletes
        # are idempotent; only remove the row after every cleanup step succeeds.
        _delete_document_minio_images(db, tenant_id=tenant_id, document_id=document_id, document=document)
        _get_indexer_class()(db).delete_chunk_indexes(
            tenant_id=tenant_id,
            document_id=document_id,
            strict=True,
        )
        _delete_document_table_store(tenant_id=tenant_id, document_id=document_id, document=document)
        _delete_document_file(tenant_id=tenant_id, document=document)
        _cleanup_document_kg_artifacts(db, tenant_id=tenant_id, document_id=document_id)
        _touch_dataset_updated_after_delete(db, tenant_id=tenant_id, document=document)
        _delete_document_record(
            db,
            tenant_id=tenant_id,
            account_id=account_id,
            document_id=document_id,
            document=document,
        )
    except Exception:
        with contextlib.suppress(Exception):
            db.rollback()
        raise


async def _delete_document_lifecycle(
    *,
    document_id: UUID,
    tenant_id: UUID,
    account_id: str,
    db: Session,
    enforce_permissions: bool = True,
    enforce_membership: bool = True,
    session_factory: Callable[[], Session] | None = None,
) -> None:
    """
    Internal document delete lifecycle shared by API and background jobs.

    - `enforce_permissions=True` matches the public endpoint behavior.
    - `enforce_permissions=False` is intended for admin-only lifecycle operations.
    """
    factory = session_factory or SessionLocal
    task_ids = await _run_delete_step_without_blocking_event_loop(
        _run_document_delete_session_step,
        factory,
        _prepare_document_delete,
        {
            "document_id": document_id,
            "tenant_id": tenant_id,
            "account_id": account_id,
            "enforce_permissions": bool(enforce_permissions),
            "enforce_membership": bool(enforce_membership),
        },
    )
    await _abort_document_tasks_before_delete(document_id=document_id, task_ids=task_ids)
    try:
        await _run_delete_step_without_blocking_event_loop(
            _run_document_delete_session_step,
            factory,
            _cleanup_document_after_tombstone,
            {
                "document_id": document_id,
                "tenant_id": tenant_id,
                "account_id": account_id,
            },
        )
    finally:
        # Callers may keep their request/job session for subsequent work. Ensure
        # it does not retain stale ORM state written by the isolated sessions.
        with contextlib.suppress(Exception):
            db.expire_all()

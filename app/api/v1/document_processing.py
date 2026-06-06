from __future__ import annotations

import asyncio
import contextlib
import importlib
import uuid
from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.api.schemas.document import DocumentStatus
from app.core.database import get_db
from app.models.dataset import Dataset
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
async def get_document_status(
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
    document = (
        db.query(DBDocument)
        .filter(DBDocument.id == document_id, DBDocument.tenant_id == tenant_id)
        .first()
    )

    if not document:
        raise HTTPException(status_code=404, detail=documents_module.DOC_NOT_FOUND_DETAIL)

    dataset: Dataset | None = None
    if document.dataset_id:
        dataset = documents_module.DatasetService.get_dataset(db, tenant_id, document.dataset_id)
        documents_module.DatasetService.assert_dataset_readable(db, dataset, account_id)
    documents_module._assert_document_acl_readable(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        document=document,
        dataset=dataset,
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

    document = (
        db.query(DBDocument)
        .filter(DBDocument.id == document_id, DBDocument.tenant_id == tenant_id)
        .first()
    )
    if not document:
        raise HTTPException(status_code=404, detail=documents_module.DOC_NOT_FOUND_DETAIL)

    if document.dataset_id:
        dataset = documents_module.DatasetService.get_dataset(db, tenant_id, document.dataset_id)
        documents_module.DatasetService.assert_dataset_writable(db, dataset, account_id)

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
        try:
            from arq.jobs import Job
        except ImportError as exc:
            documents_module.logger.warning(
                "TASK_QUEUE_ENABLED=true but arq is missing; cannot abort tasks %s for document %s: %s (hint: pip install arq)",
                task_ids,
                document_id,
                str(exc)[:200],
            )
        else:
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


@router.post("/{document_id}/retry", response_model=DocumentStatus, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def retry_document_processing(
    document_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    force: bool = False,
    skip_if_unchanged: bool = False,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Retry a failed/cancelled document processing task.

    Notes:
    - This will delete existing chunks (DB) and indexes (vector/BM25/KG) before reprocessing.
    - Use `force=true` to allow retrying completed documents.
    """
    documents_module = _documents_module()
    documents_module.DatasetService.ensure_member(db, tenant_id, account_id)

    document = (
        db.query(DBDocument)
        .filter(DBDocument.id == document_id, DBDocument.tenant_id == tenant_id)
        .first()
    )
    if not document:
        raise HTTPException(status_code=404, detail=documents_module.DOC_NOT_FOUND_DETAIL)

    if document.dataset_id:
        dataset = documents_module.DatasetService.get_dataset(db, tenant_id, document.dataset_id)
        documents_module.DatasetService.assert_dataset_writable(db, dataset, account_id)

    current_status = str(document.status or "").lower()
    if current_status == "processing" or (
        current_status == "pending"
        and not documents_module._is_uploaded_only_pending_document(document)
    ):
        raise HTTPException(status_code=409, detail=f"Cannot retry a {current_status} document")
    if current_status == "completed" and not force:
        raise HTTPException(status_code=409, detail="Document is already completed (use force=true to reprocess)")

    raw_path = str(document.file_path or "").strip()
    if not raw_path or raw_path.startswith(documents_module.MANUAL_FILE_PATH_PREFIX):
        raise HTTPException(status_code=409, detail="Document file is not reprocessable")

    if skip_if_unchanged and current_status == "completed" and force:
        meta0 = dict(document.doc_metadata or {})
        file_sha = str(meta0.get("file_sha256") or "").strip().lower()
        ready0 = bool(meta0.get("active_pipeline_ready")) if "active_pipeline_ready" in meta0 else True
        active0 = str(meta0.get("active_pipeline_hash") or meta0.get("pipeline_hash") or "").strip()
        if file_sha and ready0 and active0:
            try:
                computed0 = documents_module._compute_pipeline_hash(meta0)
            except Exception:
                computed0 = ""
            if computed0 and computed0 == active0:
                target_key = f"{document_id}:{active0}"
                exists = None
                try:
                    exists = (
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
                    exists = None
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
                            exists = True
                            break

                if exists:
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

    object_name: str | None = None
    file_path: Path | None = None
    if documents_module.is_minio_uri(raw_path):
        if not bool(getattr(documents_module.settings, "MINIO_ENABLED", False)):
            raise HTTPException(status_code=503, detail="Object storage is disabled")
        try:
            ref = documents_module.parse_minio_uri(raw_path)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=documents_module.DOCUMENT_FILE_NOT_FOUND_DETAIL) from exc
        if ref.bucket != str(getattr(documents_module.settings, "MINIO_BUCKET_NAME", "")):
            raise HTTPException(status_code=403, detail=documents_module.DOCUMENT_FILE_ACCESS_DENIED_DETAIL)
        dataset_id = str(document.dataset_id) if document.dataset_id else str(tenant_id)
        expected_object = documents_module.minio_service.build_document_object_name(
            tenant_id=str(tenant_id),
            dataset_id=dataset_id,
            document_id=str(document.id),
            extension=f".{(document.file_type or '').lower()}",
        )
        if ref.object_name != expected_object:
            raise HTTPException(status_code=403, detail=documents_module.DOCUMENT_FILE_ACCESS_DENIED_DETAIL)
        try:
            documents_module.minio_service.stat_object(object_name=ref.object_name)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=404, detail=documents_module.DOCUMENT_FILE_NOT_FOUND_DETAIL) from exc
        object_name = ref.object_name
    else:
        file_path = Path(raw_path)
        if not file_path.exists() or not file_path.is_file():
            raise HTTPException(status_code=404, detail=documents_module.DOCUMENT_FILE_NOT_FOUND_DETAIL)

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

    preserve_existing_versions = bool(meta.get("active_pipeline_ready")) and pipeline_hash != active_pipeline_hash

    cleanup_chunk_ids: list[UUID] = []
    if preserve_existing_versions:
        target_key = f"{document_id}:{pipeline_hash}"

        with contextlib.suppress(Exception):
            rows = (
                db.query(DocumentChunk.id)
                .filter(
                    DocumentChunk.document_id == document_id,
                    DocumentChunk.tenant_id == tenant_id,
                    DocumentChunk.doc_metadata["doc_pipeline_key"].astext == target_key,  # type: ignore[attr-defined]
                )
                .all()
            )
            cleanup_chunk_ids = [chunk_id for (chunk_id,) in rows if isinstance(chunk_id, UUID)]

        with contextlib.suppress(Exception):
            from app.storage.vector.factory import get_vector_store

            get_vector_store().delete_by_document_id_and_filter(
                document_id=document_id,
                tenant_id=tenant_id,
                metadata_filter={"doc_pipeline_key": {"$eq": target_key}},
            )
        with contextlib.suppress(Exception):
            from app.rag.retriever import hybrid_retriever

            hybrid_retriever.remove_from_bm25_index_by_metadata_filter(
                tenant_id=tenant_id,
                metadata_filter={"doc_pipeline_key": {"$eq": target_key}},
            )
        with contextlib.suppress(Exception):
            db.query(DocumentChunk).filter(
                DocumentChunk.document_id == document_id,
                DocumentChunk.tenant_id == tenant_id,
                DocumentChunk.doc_metadata["doc_pipeline_key"].astext == target_key,  # type: ignore[attr-defined]
            ).delete(synchronize_session=False)
    else:
        with contextlib.suppress(Exception):
            documents_module.Indexer(db).delete_chunk_indexes(tenant_id=tenant_id, document_id=document_id)
        with contextlib.suppress(Exception):
            db.query(DocumentChunk).filter(
                DocumentChunk.document_id == document_id,
                DocumentChunk.tenant_id == tenant_id,
            ).delete(synchronize_session=False)
        meta.pop("img_ids", None)

    document.doc_metadata = meta
    document.status = "pending"
    document.processing_progress = 0
    document.current_stage = "queued"
    document.failed_stage = None
    document.error_code = None
    document.next_retry_at = None
    document.error_message = None
    if not preserve_existing_versions:
        document.chunk_count = 0
        document.total_characters = 0
    db.commit()
    db.refresh(document)

    if preserve_existing_versions and cleanup_chunk_ids:
        try:
            from app.rag.kg.models import KgRelation

            db.query(KgRelation).filter(
                KgRelation.tenant_id == tenant_id,
                KgRelation.chunk_id.in_(cleanup_chunk_ids),
            ).delete(synchronize_session=False)

            documents_module.Indexer(db).delete_event_indexes_for_chunks(
                tenant_id=tenant_id,
                chunk_ids=cleanup_chunk_ids,
                commit=False,
                prune_orphan_entities=True,
            )
            db.commit()
        except Exception:
            with contextlib.suppress(Exception):
                db.rollback()

    if not preserve_existing_versions:
        try:
            from app.rag.kg.models import KgRelation

            db.query(KgRelation).filter(
                KgRelation.tenant_id == tenant_id,
                KgRelation.document_id == document_id,
            ).delete(synchronize_session=False)

            documents_module.Indexer(db).delete_event_indexes(
                tenant_id=tenant_id,
                document_id=document_id,
                commit=False,
                prune_orphan_entities=True,
            )
            db.commit()
        except Exception:
            with contextlib.suppress(Exception):
                db.rollback()

    job_id = f"doc:{tenant_id}:{document_id}:{pipeline_hash}"
    task_id = await documents_module.enqueue_document_processing(
        tenant_id=tenant_id,
        document_id=document_id,
        requested_by=account_id,
        job_id=job_id,
    )
    if task_id:
        meta = dict(document.doc_metadata or {})
        meta["task_id"] = task_id
        document.doc_metadata = meta
        db.commit()
        db.refresh(document)
    else:
        if file_path is not None:
            background_tasks.add_task(
                documents_module.run_document_processing_limited,
                file_path,
                document_id,
                tenant_id,
                meta.get("parser_backend"),
                meta.get("chunk_strategy"),
            )
        else:
            temp_dir = (Path(documents_module.settings.UPLOAD_DIR) / str(tenant_id) / ".tmp").resolve(strict=False)
            suffix = f".{(document.file_type or '').lower()}"
            temp_path = temp_dir / f"{document_id}.{uuid.uuid4().hex}{suffix}"

            async def _process_from_object_store() -> None:
                try:
                    await asyncio.to_thread(
                        documents_module.minio_service.download_object_to_path,
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

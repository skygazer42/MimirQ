"""Batch document ingestion with per-item sessions and precheck ownership."""

import asyncio
import contextlib
import json
import os
import shutil
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi import BackgroundTasks, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.api.schemas.document import DocumentBatchUploadResponse
from app.api.schemas.document_ingestion import (
    PipelineOptionOverrides,
    PipelineOverridesFormFields,
    UploadDocumentsBatchFormFields,
)
from app.api.utils.document_pipeline_input import parse_pipeline_json
from app.api.utils.upload import _normalize_upload_key as normalize_upload_key
from app.api.utils.upload import _normalize_upload_path_parts, save_upload_file_with_hash
from app.core.config import settings
from app.core.database import SessionLocal
from app.models.dataset import Dataset
from app.models.dataset_precheck_scan import DatasetPrecheckScanRun as DBDatasetPrecheckScanRun
from app.models.document import Document as DBDocument
from app.rag.core.logging import get_logger
from app.services import dataset_service, ingestion_run_service
from app.services import document_ingestion_policy as ingestion_plan
from app.services import document_source_persistence as source_persistence
from app.services.dataset_precheck_ingestion_suggestion import apply_ingestion_policy_suggestion
from app.services.dataset_precheck_scan_runner import run_dataset_precheck_scan
from app.services.document_identity import build_document_dedup_key
from app.services.document_index_channel_service import reconcile_document_index_channels
from app.services.document_ingestion import (
    _build_document_metadata,
    _document_upload_path,
    _maybe_acquire_ingest_lock,
    _normalize_upload_identity,
    _retain_ingest_lock_if_task_handed_off,
    _retry_failed_persisted_duplicate,
    _reuse_duplicate_document,
)
from app.services.document_ingestion import (
    _IngestLockLease as IngestLockLease,
)
from app.services.document_ingestion import (
    _PreparedDocumentMetadata as PreparedDocumentMetadata,
)
from app.services.document_ingestion import (
    _UploadIdentity as UploadIdentity,
)
from app.services.document_processing_dispatch import LocalProcessingSource, dispatch_uploaded_document
from app.services.ingestion_policy import IngestionPolicy, parse_ingestion_policy_from_metadata
from app.services.tenant_quota_service import enforce_tenant_upload_quotas
from app.storage.object.runtime import (
    document_object_store_metadata,
    get_document_object_store,
    is_object_storage_uri,
)

logger = get_logger("services.document_batch_ingestion")


def _apply_object_store_metadata_if_needed(doc_metadata: dict[str, Any], *, stored_path: str) -> None:
    if not is_object_storage_uri(stored_path):
        return
    store = get_document_object_store()
    if store is not None:
        doc_metadata.update(document_object_store_metadata(store))


def _apply_precheck_policy_suggestion(
    *,
    db: Session,
    dataset: Any,
    scan_run: Any,
    tenant_id: UUID,
) -> None:
    try:
        apply_ingestion_policy_suggestion(
            db,
            dataset=dataset,
            scan_run=scan_run,
            tenant_id=tenant_id,
            replace=False,
        )
    except HTTPException as exc:
        if exc.status_code != 409:
            db.rollback()
            logger.warning(
                "Precheck-first policy apply failed: %s",
                str(exc.detail)[:200],
                exc_info=True,
            )
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.warning("Precheck-first policy apply failed: %s", str(exc)[:200], exc_info=True)


def _build_batch_document(
    *,
    file_id: UUID,
    tenant_id: UUID,
    dataset_id: UUID | None,
    identity: UploadIdentity,
    file_size: int,
    stored_path: str,
    account_id: str,
    doc_metadata: dict[str, Any],
    file_sha256: str | None,
    pipeline_hash: str,
) -> DBDocument:
    db_document = DBDocument(
        id=file_id,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        filename=identity.filename,
        file_type=identity.file_ext.lstrip("."),
        file_size=file_size,
        file_path=stored_path,
        owner_id=account_id,
        access_mode=None,
        status="pending",
        processing_progress=0,
        doc_metadata=doc_metadata,
    )
    if settings.UPLOAD_DEDUP_ENABLED:
        db_document.dedup_key = build_document_dedup_key(content_sha256=file_sha256, pipeline_hash=pipeline_hash)
    return db_document


def _build_batch_response(
    *,
    files: list[UploadFile],
    successful: list[dict[str, Any]],
    failed: list[dict[str, Any]],
    precheck_scan_run_id: str | None = None,
) -> DocumentBatchUploadResponse:
    response = {
        "total": len(files),
        "successful_count": len(successful),
        "failed_count": len(failed),
        "successful": [
            {
                "document_id": result["document_id"],
                "filename": result["filename"],
                "source_path": result.get("source_path"),
                "status": result.get("status") or "pending",
            }
            for result in successful
        ],
        "failed": [
            {
                "filename": result.get("filename") or "unknown",
                "source_path": result.get("source_path"),
                "error": result.get("error") or "upload_failed",
            }
            for result in failed
        ],
    }
    if precheck_scan_run_id is not None:
        response["precheck_scan_run_id"] = precheck_scan_run_id
    return DocumentBatchUploadResponse.model_validate(response)


async def _cancel_gather_tasks(in_flight: dict[asyncio.Task[Any], int]) -> None:
    for task in in_flight:
        task.cancel()
    if in_flight:
        await asyncio.gather(*in_flight, return_exceptions=True)


def _cleanup_uploaded_batch_files(results: list[dict[str, Any]]) -> None:
    for result in results:
        source_persistence.unlink_source(Path(result["file_path"]))


def _coerce_batch_result(result: Any) -> dict[str, Any]:
    if isinstance(result, dict):
        return result
    if isinstance(result, Exception):
        return _failure_result(filename="unknown", source_path=None, error=result)
    return _failure_result(filename="unknown", source_path=None, error="upload_failed")


def _consume_gather_results(
    done: set[asyncio.Task[Any]],
    *,
    in_flight: dict[asyncio.Task[Any], int],
    results: list[Any],
) -> None:
    for task in done:
        index = in_flight.pop(task)
        try:
            results[index] = task.result()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            results[index] = exc


def _document_result_snapshot(document: DBDocument, *, source_path: str | None) -> dict[str, Any]:
    return {
        "document_id": str(document.id),
        "filename": str(document.filename),
        "source_path": source_path,
        "status": str(document.status),
        "doc_metadata": dict(document.doc_metadata or {}),
    }


def _failure_result(*, filename: str, source_path: str | None, error: Any, limit: int = 200) -> dict[str, Any]:
    return {
        "success": False,
        "filename": filename or "unknown",
        "source_path": source_path,
        "error": str(error)[:limit] if error is not None else "upload_failed",
    }


async def _finalize_batch_document(
    *,
    background_tasks: BackgroundTasks,
    db: Session,
    document: DBDocument,
    file_path: Path,
    pipeline_hash: str,
    resolved_pipeline: ingestion_plan.ResolvedUploadPipeline,
    upload_only: bool,
    ingest_lock: IngestLockLease,
) -> DBDocument:
    if upload_only:
        with contextlib.suppress(Exception):
            reconcile_document_index_channels(
                db,
                document=document,
                pipeline_hash=pipeline_hash,
                reset_enabled_to_pending=True,
                commit=True,
            )
        if is_object_storage_uri(document.file_path):
            source_persistence.unlink_source(file_path)
        return document
    with contextlib.suppress(Exception):
        reconcile_document_index_channels(
            db,
            document=document,
            pipeline_hash=pipeline_hash,
            reset_enabled_to_pending=True,
            commit=True,
        )
    keep_local_file = await dispatch_uploaded_document(
        background_tasks=background_tasks,
        source=LocalProcessingSource(file_path),
        tenant_id=document.tenant_id,
        requested_by=document.owner_id,
        pipeline_hash=pipeline_hash,
        parser_backend=resolved_pipeline.resolved_parser_backend,
        chunk_strategy=resolved_pipeline.resolved_chunk_strategy,
        db=db,
        document=document,
    )
    if not keep_local_file:
        source_persistence.unlink_source(file_path)
    _retain_ingest_lock_if_task_handed_off(document, ingest_lock=ingest_lock)
    return document


def _finalize_batch_ingestion_run(
    *,
    db: Session,
    tenant_id: UUID,
    ingestion_run: Any,
    files: list[UploadFile],
    successful: list[dict[str, Any]],
    failed: list[dict[str, Any]],
) -> None:
    if ingestion_run is None:
        return
    for result in successful:
        doc_id_raw = result["document_id"].strip()
        if not doc_id_raw:
            continue
        try:
            doc_id = UUID(doc_id_raw)
        except ValueError:
            continue
        doc = (
            db.query(DBDocument)
            .filter(
                DBDocument.id == doc_id,
                DBDocument.tenant_id == tenant_id,
            )
            .first()
        )
        if doc is None:
            continue
        try:
            meta0 = dict(doc.doc_metadata or {})
            meta0["last_ingestion_run_id"] = str(ingestion_run.id)
            meta0["last_ingestion_kind"] = "upload_batch"
            doc.doc_metadata = meta0
            db.commit()
            db.refresh(doc)
        except Exception:
            db.rollback()
            logger.warning(
                "Batch document persisted but ingestion-run metadata update failed: "
                "tenant_id=%s document_id=%s run_id=%s",
                tenant_id,
                doc.id,
                ingestion_run.id,
                exc_info=True,
            )
            meta0 = dict(doc.doc_metadata or {})
        try:
            ingestion_run_service.add_document(
                db,
                tenant_id=tenant_id,
                run_id=ingestion_run.id,
                document_id=doc.id,
                source_ref=(result.get("source_path") or doc.filename),
                initial_status=str(result.get("status") or doc.status or "created"),
                doc_meta=meta0,
            )
        except Exception:
            db.rollback()
            logger.warning(
                "Batch document persisted but ingestion-run attachment failed: tenant_id=%s document_id=%s run_id=%s",
                tenant_id,
                doc.id,
                ingestion_run.id,
                exc_info=True,
            )
    try:
        ingestion_run_service.close_intake(
            db,
            tenant_id=tenant_id,
            run_id=ingestion_run.id,
            attempted_inputs=len(files),
            rejected_inputs=len(failed),
            rejection_reasons=[result.get("error") for result in failed],
        )
    except Exception:
        db.rollback()
        logger.warning(
            "Batch ingestion-run intake close failed: tenant_id=%s run_id=%s",
            tenant_id,
            ingestion_run.id,
            exc_info=True,
        )


async def _gather_with_concurrency_limit(
    factories: list[Callable[[], Awaitable[Any]]],
    *,
    limit: int,
) -> list[Any]:
    if limit <= 0:
        raise ValueError("limit must be at least 1")

    results: list[Any] = [None] * len(factories)
    in_flight: dict[asyncio.Task[Any], int] = {}
    next_index = _schedule_gather_tasks(factories, in_flight=in_flight, limit=limit, next_index=0)
    try:
        while in_flight:
            done, _ = await asyncio.wait(in_flight, return_when=asyncio.FIRST_COMPLETED)
            _consume_gather_results(done, in_flight=in_flight, results=results)
            next_index = _schedule_gather_tasks(factories, in_flight=in_flight, limit=limit, next_index=next_index)
    except BaseException:
        await _cancel_gather_tasks(in_flight)
        raise

    return results


def _link_precheck_staging_tree(staged_successful: list[dict[str, Any]], *, staging_root: Path) -> bool:

    linked_any = False
    staging_root_resolved = staging_root.resolve(strict=False)
    for idx, item in enumerate(staged_successful):
        src_raw = item["file_path"].strip()
        if not src_raw:
            continue
        src = Path(src_raw).resolve(strict=False)
        if not src.exists() or not src.is_file():
            continue
        dst = (staging_root / _safe_staging_relpath(item, idx=idx)).resolve(strict=False)
        try:
            dst.relative_to(staging_root_resolved)
        except Exception:
            dst = (staging_root / f"FILE_{idx:06d}{item['file_ext'].strip().lower()}").resolve(
                strict=False
            )
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.exists():
            suffix = item["file_id"].hex
            dst = dst.with_name(f"{dst.stem}.{suffix}{dst.suffix}")
        try:
            os.link(src, dst)
            linked_any = True
        except Exception:
            try:
                shutil.copy2(src, dst)
                linked_any = True
            except Exception:
                logger.debug("Skipping item after non-critical exception", exc_info=True)
    return linked_any


async def _maybe_resolve_upload_duplicate(
    *,
    db: Session,
    background_tasks: BackgroundTasks,
    tenant_id: UUID,
    account_id: str,
    dataset_id: UUID | None,
    identity: UploadIdentity,
    request_parser_backend: str,
    request_chunk_strategy: str,
    resolved_pipeline: ingestion_plan.ResolvedUploadPipeline,
    pipeline_hash: str,
    file_sha256: str | None,
    user_patch: dict[str, Any] | None,
    upload_only: bool,
    file_path: Path,
    ingest_lock: IngestLockLease,
    cleanup_exact_duplicate: bool,
) -> DBDocument | None:
    if not settings.UPLOAD_DEDUP_ENABLED or not isinstance(file_sha256, str) or not file_sha256:
        return None
    duplicate = source_persistence.find_duplicate_document(
        db,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        file_sha256=file_sha256,
        pipeline_hash=pipeline_hash,
    )
    if duplicate is not None and duplicate.status.lower() != "failed":
        if cleanup_exact_duplicate:
            source_persistence.unlink_source(file_path)
        return duplicate
    duplicate_by_sha = source_persistence.find_duplicate_document_by_sha(
        db,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        file_sha256=file_sha256,
    )
    if duplicate_by_sha is None:
        return None
    source_persistence.unlink_source(file_path)
    return await _reuse_duplicate_document(
        duplicate_by_sha,
        db=db,
        identity=identity,
        request_parser_backend=request_parser_backend,
        request_chunk_strategy=request_chunk_strategy,
        resolved_pipeline=resolved_pipeline,
        pipeline_hash=pipeline_hash,
        file_sha256=file_sha256,
        user_patch=user_patch,
        upload_only=upload_only,
        background_tasks=background_tasks,
        tenant_id=tenant_id,
        account_id=account_id,
        ingest_lock=ingest_lock,
    )


def _parse_batch_user_metadata_map(user_metadata_map: str | None) -> dict[str, dict[str, Any]]:

    user_meta_by_key: dict[str, dict[str, Any]] = {}
    if not isinstance(user_metadata_map, str) or not user_metadata_map.strip():
        return user_meta_by_key
    raw = user_metadata_map.strip()
    max_len = settings.USER_METADATA_MAP_FORM_JSON_MAX_CHARS
    if max_len > 0 and len(raw) > max_len:
        raise HTTPException(status_code=400, detail="user_metadata_map is too large")
    try:
        obj = json.loads(raw)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail="Invalid user_metadata_map JSON (expect UTF-8)") from exc
    if not isinstance(obj, dict):
        raise HTTPException(status_code=400, detail="user_metadata_map must be a JSON object")
    for key, value in obj.items():
        if not isinstance(key, str) or not isinstance(value, dict):
            continue
        normalized = normalize_upload_key(key)
        if normalized:
            user_meta_by_key[normalized] = value
    return user_meta_by_key


def _partition_batch_results(results: list[Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    processed = [_coerce_batch_result(result) for result in results]
    return [result for result in processed if result.get("success")], [
        result for result in processed if not result.get("success")
    ]


async def _process_live_batch_upload(
    *,
    background_tasks: BackgroundTasks,
    db: Session,
    tenant_id: UUID,
    account_id: str,
    dataset: Any,
    dataset_meta: Any,
    policy: Any,
    pipeline_parsed: Any,
    pipeline_overrides: Any,
    defaults: ingestion_plan.UploadDefaultSelection,
    file: UploadFile,
    user_meta_by_key: dict[str, dict[str, Any]],
    request_parser_backend: str,
    request_chunk_strategy: str,
    upload_only: bool,
    governance_profile_cache: dict[str, Any],
) -> dict[str, Any]:
    try:
        identity = _normalize_upload_identity(file)
        if not _upload_extension_allowed(identity.file_ext):
            return _failure_result(
                filename=identity.filename,
                source_path=identity.source_path,
                error=f"Unsupported file type: {identity.file_ext}",
            )
        file_id = uuid.uuid4()
        file_path = _document_upload_path(tenant_id, file_id, identity.file_ext)
        file_size, file_sha256 = await save_upload_file_with_hash(
            file,
            file_path,
            max_bytes=settings.MAX_FILE_SIZE,
        )

        try:
            enforce_tenant_upload_quotas(
                db,
                tenant_id=tenant_id,
                additional_docs=1,
                additional_bytes=file_size,
            )
        except HTTPException as exc:
            source_persistence.unlink_source(file_path)
            return _failure_result(
                filename=identity.filename,
                source_path=identity.source_path,
                error=str(exc.detail or "tenant_quota_exceeded"),
            )
        return await _process_saved_batch_upload(
            background_tasks=background_tasks,
            db=db,
            tenant_id=tenant_id,
            account_id=account_id,
            dataset=dataset,
            dataset_meta=dataset_meta,
            policy=policy,
            pipeline_parsed=pipeline_parsed,
            pipeline_overrides=pipeline_overrides,
            defaults=defaults,
            identity=identity,
            file_id=file_id,
            file_path=file_path,
            file_size=file_size,
            file_sha256=(file_sha256),
            content_type=file.content_type or "application/octet-stream",
            request_parser_backend=request_parser_backend,
            request_chunk_strategy=request_chunk_strategy,
            user_patch=_select_upload_user_patch(
                user_meta_by_key=user_meta_by_key,
                upload_key=identity.upload_key,
                filename=identity.filename,
            ),
            upload_only=upload_only,
            governance_profile_cache=governance_profile_cache,
        )
    finally:
        with contextlib.suppress(Exception):
            db.close()


async def _process_saved_batch_upload(
    *,
    background_tasks: BackgroundTasks,
    db: Session,
    tenant_id: UUID,
    account_id: str,
    dataset: Any,
    dataset_meta: Any,
    policy: Any,
    pipeline_parsed: Any,
    pipeline_overrides: Any,
    defaults: ingestion_plan.UploadDefaultSelection,
    identity: UploadIdentity,
    file_id: UUID,
    file_path: Path,
    file_size: int,
    file_sha256: str | None,
    content_type: str,
    request_parser_backend: str,
    request_chunk_strategy: str,
    user_patch: dict[str, Any] | None,
    upload_only: bool,
    governance_profile_cache: dict[str, Any],
) -> dict[str, Any]:
    ingest_lock = IngestLockLease()
    prepared_metadata = PreparedDocumentMetadata(doc_metadata={}, pipeline_hash="")
    stored_path: str | None = None
    persistence_started = False
    try:
        resolved_pipeline = ingestion_plan.resolve_upload_pipeline(
            db=db,
            tenant_id=tenant_id,
            dataset_meta=dataset_meta,
            policy=policy,
            filename=identity.upload_key or identity.filename,
            file_ext=identity.file_ext,
            pipeline_parsed=pipeline_parsed,
            pipeline_overrides=pipeline_overrides,
            defaults=defaults,
            governance_profile_cache=governance_profile_cache,
        )
        prepared_metadata = _build_document_metadata(
            identity=identity,
            request_parser_backend=request_parser_backend,
            request_chunk_strategy=request_chunk_strategy,
            resolved_pipeline=resolved_pipeline,
            file_sha256=file_sha256,
            user_patch=user_patch,
            upload_only=upload_only,
        )
        await _maybe_acquire_ingest_lock(
            tenant_id=tenant_id,
            dataset_id=dataset.id if dataset is not None else None,
            file_sha256=file_sha256,
            pipeline_hash=prepared_metadata.pipeline_hash,
            account_id=account_id,
            doc_metadata=prepared_metadata.doc_metadata,
            ingest_lock=ingest_lock,
        )
        duplicate = await _maybe_resolve_upload_duplicate(
            db=db,
            background_tasks=background_tasks,
            tenant_id=tenant_id,
            account_id=account_id,
            dataset_id=dataset.id if dataset is not None else None,
            identity=identity,
            request_parser_backend=request_parser_backend,
            request_chunk_strategy=request_chunk_strategy,
            resolved_pipeline=resolved_pipeline,
            pipeline_hash=prepared_metadata.pipeline_hash,
            file_sha256=file_sha256,
            user_patch=user_patch,
            upload_only=upload_only,
            file_path=file_path,
            ingest_lock=ingest_lock,
            cleanup_exact_duplicate=True,
        )
        if duplicate is not None:
            return _success_result(filename=identity.filename, source_path=identity.source_path, document=duplicate)
        stored_path = await source_persistence.store_document_source(
            file_path=file_path,
            tenant_id=tenant_id,
            dataset_id=dataset.id if dataset is not None else tenant_id,
            document_id=file_id,
            extension=identity.file_ext,
            content_type=content_type,
        )
        _apply_object_store_metadata_if_needed(prepared_metadata.doc_metadata, stored_path=stored_path)
        db_document = _build_batch_document(
            file_id=file_id,
            tenant_id=tenant_id,
            dataset_id=dataset.id if dataset is not None else None,
            identity=identity,
            file_size=file_size,
            stored_path=stored_path,
            account_id=account_id,
            doc_metadata=prepared_metadata.doc_metadata,
            file_sha256=file_sha256,
            pipeline_hash=prepared_metadata.pipeline_hash,
        )
        persistence_started = True
        try:
            await source_persistence.persist_uploaded_document(db, db_document, file_path=file_path)
        except source_persistence.DuplicatePersistedDocumentError as exc:
            await _retry_failed_persisted_duplicate(
                exc.document,
                background_tasks=background_tasks,
                tenant_id=tenant_id,
                account_id=account_id,
                db=db,
            )
            _retain_ingest_lock_if_task_handed_off(exc.document, ingest_lock=ingest_lock)
            return _success_result(filename=identity.filename, source_path=identity.source_path, document=exc.document)
        document = await _finalize_batch_document(
            background_tasks=background_tasks,
            db=db,
            document=db_document,
            file_path=file_path,
            pipeline_hash=prepared_metadata.pipeline_hash,
            resolved_pipeline=resolved_pipeline,
            upload_only=upload_only,
            ingest_lock=ingest_lock,
        )
        return _success_result(filename=identity.filename, source_path=identity.source_path, document=document)
    except Exception as exc:  # noqa: BLE001
        if not persistence_started and stored_path is not None:
            await source_persistence.cleanup_unpersisted_source(
                stored_path, document_metadata=prepared_metadata.doc_metadata
            )
        if not persistence_started or (stored_path is not None and is_object_storage_uri(stored_path)):
            source_persistence.unlink_source(file_path)
        logger.exception("Error processing file %s: %s", identity.filename, str(exc)[:200])
        return _failure_result(filename=identity.filename, source_path=identity.source_path, error=exc)
    finally:
        await ingest_lock.cleanup()
        with contextlib.suppress(Exception):
            db.close()


def _refresh_batch_policy(dataset: Dataset) -> IngestionPolicy | None:
    dataset_meta = (dataset.dataset_metadata or {}) if dataset is not None else {}
    return parse_ingestion_policy_from_metadata(dataset_meta if isinstance(dataset_meta, dict) else {})


async def _run_precheck_scan(
    *,
    db: Session,
    tenant_id: UUID,
    account_id: str,
    dataset: Any,
    staged_successful: list[dict[str, Any]],
    precheck_only: bool,
) -> Any:
    upload_dir = Path(settings.UPLOAD_DIR) / str(tenant_id)
    staging_root = (upload_dir / ".tmp" / "precheck_ingest" / uuid.uuid4().hex).resolve(strict=False)
    staging_root.mkdir(parents=True, exist_ok=True)
    scan_run = None
    try:
        if not _link_precheck_staging_tree(staged_successful, staging_root=staging_root):
            return None
        scan_run = DBDatasetPrecheckScanRun(
            tenant_id=tenant_id,
            dataset_id=dataset.id,
            requested_by=account_id,
            kind="path",
            status="pending",
            progress=0,
            config={
                "root_path": str(staging_root),
                "max_files": len(staged_successful),
                "enable_pdf_quality": True,
                "enable_text_extract": True,
                "enable_pii": False,
                "enable_secrets": False,
                "compute_file_hash": False,
                "redact_paths": False,
                "enable_sampling": True,
                "sample_size": None,
                "enable_near_dup": False,
                "internal_allow_upload_scan": True,
            },
            summary={},
            artifacts={},
        )
        try:
            db.add(scan_run)
            db.commit()
        except Exception:  # noqa: BLE001 - optional precheck creation may fail independently
            db.rollback()
            if precheck_only:
                raise
            logger.warning("Precheck run creation failed; continuing without precheck", exc_info=True)
            return None
        db.refresh(scan_run)
        try:
            await asyncio.to_thread(
                _run_precheck_scan_job,
                tenant_id=tenant_id,
                dataset_id=dataset.id,
                scan_run_id=scan_run.id,
            )
        except Exception as exc:  # noqa: BLE001 - optional scan failure retains its persisted run
            db.rollback()
            if precheck_only:
                raise
            logger.warning("Precheck-first scan failed; retaining its run: %s", str(exc)[:200], exc_info=True)
            return scan_run
        db.refresh(scan_run)
        if not precheck_only:
            _apply_precheck_policy_suggestion(
                db=db,
                dataset=dataset,
                scan_run=scan_run,
                tenant_id=tenant_id,
            )
        return scan_run
    finally:
        with contextlib.suppress(Exception):
            shutil.rmtree(staging_root)


def _run_precheck_scan_job(
    *,
    tenant_id: UUID,
    dataset_id: UUID,
    scan_run_id: UUID,
) -> None:
    db2 = SessionLocal()
    try:
        run_dataset_precheck_scan(
            db2,
            tenant_id=tenant_id,
            dataset_id=dataset_id,
            scan_run_id=scan_run_id,
        )
    except Exception as exc:  # noqa: BLE001
        db2.rollback()
        try:
            row = (
                db2.query(DBDatasetPrecheckScanRun)
                .filter(
                    DBDatasetPrecheckScanRun.id == scan_run_id,
                    DBDatasetPrecheckScanRun.tenant_id == tenant_id,
                    DBDatasetPrecheckScanRun.dataset_id == dataset_id,
                )
                .first()
            )
            if row is not None:
                row.status = "failed"
                row.error_message = str(exc)[:200]
                row.finished_at = datetime.now(UTC)
                db2.commit()
        except Exception as mark_exc:  # noqa: BLE001
            db2.rollback()
            logger.warning(
                "Failed to mark precheck scan run as failed: %s",
                str(mark_exc)[:200],
                exc_info=True,
            )
        raise
    finally:
        db2.close()


def _safe_staging_relpath(item: dict[str, Any], *, idx: int) -> Path:

    raw = str(item.get("upload_key") or item.get("filename") or f"FILE_{idx:06d}").strip()
    parts = _normalize_upload_path_parts(raw)
    if not parts:
        parts = [str(item.get("filename") or f"FILE_{idx:06d}")]
    safe_parts: list[str] = []
    for segment in parts:
        safe_segment = segment.replace("\\", "/").strip().rsplit("/", 1)[-1]
        safe_segment = "".join(ch for ch in safe_segment if ord(ch) >= 32 and ch != "\x7f")
        if not safe_segment or safe_segment in {".", ".."}:
            safe_segment = "item"
        safe_parts.append(safe_segment[:120] if len(safe_segment) > 120 else safe_segment)
    file_ext = item["file_ext"].strip().lower()
    if safe_parts and file_ext and not safe_parts[-1].lower().endswith(file_ext):
        safe_parts[-1] = f"{safe_parts[-1]}{file_ext}"
    relpath = Path(*safe_parts) if safe_parts else Path(f"FILE_{idx:06d}{file_ext}")
    return Path(*[part for part in relpath.parts if part not in {"", ".."}])


def _schedule_gather_tasks(
    factories: list[Callable[[], Awaitable[Any]]],
    *,
    in_flight: dict[asyncio.Task[Any], int],
    limit: int,
    next_index: int,
) -> int:
    while next_index < len(factories) and len(in_flight) < limit:
        in_flight[asyncio.create_task(factories[next_index]())] = next_index
        next_index += 1
    return next_index


def _select_upload_user_patch(
    *,
    user_meta_by_key: dict[str, dict[str, Any]],
    upload_key: str,
    filename: str,
) -> dict[str, Any] | None:
    if upload_key:
        user_patch = user_meta_by_key.get(upload_key)
        if user_patch is not None:
            return user_patch
        if "/" in upload_key:
            by_basename = user_meta_by_key.get(upload_key.rsplit("/", 1)[-1])
            if by_basename is not None:
                return by_basename
    return user_meta_by_key.get(filename)


async def _stage_upload_for_precheck(
    file: UploadFile,
    *,
    tenant_id: UUID,
) -> dict[str, Any]:

    identity = _normalize_upload_identity(file)
    if not _upload_extension_allowed(identity.file_ext):
        return _failure_result(
            filename=identity.filename,
            source_path=identity.source_path,
            error=f"Unsupported file type: {identity.file_ext}",
        )
    file_id = uuid.uuid4()
    file_path = _document_upload_path(tenant_id, file_id, identity.file_ext)
    try:
        file_size, file_sha256 = await save_upload_file_with_hash(
            file,
            file_path,
            max_bytes=settings.MAX_FILE_SIZE,
        )
    except HTTPException as exc:
        source_persistence.unlink_source(file_path)
        return _failure_result(
            filename=identity.filename,
            source_path=identity.source_path,
            error=str(exc.detail or str(exc) or "upload_failed"),
        )
    except asyncio.CancelledError:
        source_persistence.unlink_source(file_path)
        raise
    except Exception as exc:  # noqa: BLE001
        source_persistence.unlink_source(file_path)
        return _failure_result(filename=identity.filename, source_path=identity.source_path, error=exc)
    return {
        "success": True,
        "filename": identity.filename,
        "source_path": identity.source_path,
        "upload_key": identity.upload_key,
        "file_ext": identity.file_ext,
        "file_id": file_id,
        "file_path": str(file_path),
        "file_size": file_size,
        "file_sha256": (file_sha256),
        "content_type": file.content_type or "application/octet-stream",
    }


def _success_result(*, filename: str, source_path: str | None, document: DBDocument) -> dict[str, Any]:
    return {"success": True, "filename": filename, **_document_result_snapshot(document, source_path=source_path)}


def _unlink_upload(path: Path) -> None:
    with contextlib.suppress(OSError):
        path.unlink(missing_ok=True)


def _upload_extension_allowed(file_ext: str) -> bool:
    return file_ext in settings.allowed_extensions_list


def _validate_batch_upload_request(files: list[UploadFile], *, max_concurrent: int) -> int:
    if not files:
        raise HTTPException(status_code=400, detail="No files provided")
    if len(files) > 50:
        raise HTTPException(status_code=400, detail="Too many files. Maximum 50 files per batch.")
    max_concurrent_raw = int(max_concurrent or 0)
    if max_concurrent_raw <= 0:
        raise HTTPException(status_code=400, detail="max_concurrent must be at least 1")
    return min(max_concurrent_raw, 10)


async def ingest_batch(
    *,
    background_tasks: BackgroundTasks,
    files: list[UploadFile],
    form: UploadDocumentsBatchFormFields,
    overrides_form: PipelineOverridesFormFields,
    tenant_id: UUID,
    account_id: str,
    db: Session,
) -> DocumentBatchUploadResponse:
    max_concurrent = _validate_batch_upload_request(files, max_concurrent=form.max_concurrent)
    enforce_tenant_upload_quotas(
        db,
        tenant_id=tenant_id,
        additional_docs=len(files),
        additional_bytes=0,
    )
    pipeline_overrides = PipelineOptionOverrides(**asdict(overrides_form))
    parser_backend = form.parser_backend
    chunk_strategy = form.chunk_strategy
    precheck_first = form.precheck_first
    precheck_only = form.precheck_only
    upload_only = form.upload_only
    pipeline_parsed = parse_pipeline_json(form.pipeline)
    user_meta_by_key = _parse_batch_user_metadata_map(form.user_metadata_map)
    dataset = dataset_service.resolve_writable_dataset(db, tenant_id, account_id, form.dataset_id)
    dataset_meta = (dataset.dataset_metadata or {}) if dataset is not None else {}
    policy = _refresh_batch_policy(dataset)
    dataset_default_pb, dataset_default_cs = ingestion_plan.dataset_upload_defaults(dataset_meta)
    defaults = ingestion_plan.select_upload_defaults(
        parser_backend=parser_backend,
        chunk_strategy=chunk_strategy,
        dataset_default_pb=dataset_default_pb,
        dataset_default_cs=dataset_default_cs,
    )
    ingestion_run = None
    if not precheck_only and not upload_only:
        try:
            ingestion_run = ingestion_run_service.create_run(
                db,
                tenant_id=tenant_id,
                dataset_id=dataset.id if dataset is not None else None,
                requested_by=account_id,
                kind="upload_batch",
                config={
                    "files": len(files),
                    "parser_backend_requested": parser_backend[:80],
                    "chunk_strategy_requested": chunk_strategy[:80],
                    "pipeline": (
                        pipeline_parsed.model_dump(exclude_none=True) if pipeline_parsed is not None else None
                    ),
                },
                expected_documents=len(files),
            )
        except Exception:
            db.rollback()
            logger.warning(
                "Batch ingestion run creation failed; continuing without run tracking: tenant_id=%s",
                tenant_id,
                exc_info=True,
            )
            ingestion_run = None
    if precheck_first or precheck_only:
        if dataset is None:
            raise HTTPException(status_code=400, detail="dataset_id is required for precheck")
        save_results = await _gather_with_concurrency_limit(
            [lambda file=file: _stage_upload_for_precheck(file, tenant_id=tenant_id) for file in files],
            limit=max_concurrent,
        )
        staged_successful, staged_failed = _partition_batch_results(save_results)
        try:
            total_bytes = sum(result["file_size"] for result in staged_successful)
            enforce_tenant_upload_quotas(
                db,
                tenant_id=tenant_id,
                additional_docs=len(staged_successful),
                additional_bytes=total_bytes,
            )
        except HTTPException:
            _cleanup_uploaded_batch_files(staged_successful)
            raise
        scan_run = None
        if staged_successful:
            scan_run = await _run_precheck_scan(
                db=db,
                tenant_id=tenant_id,
                account_id=account_id,
                dataset=dataset,
                staged_successful=staged_successful,
                precheck_only=precheck_only,
            )
        if not precheck_only and dataset is not None:
            db.refresh(dataset)
            dataset_meta = (dataset.dataset_metadata or {}) if dataset is not None else {}
            policy = _refresh_batch_policy(dataset)
            dataset_default_pb, dataset_default_cs = ingestion_plan.dataset_upload_defaults(dataset_meta)
            defaults = ingestion_plan.select_upload_defaults(
                parser_backend=parser_backend,
                chunk_strategy=chunk_strategy,
                dataset_default_pb=dataset_default_pb,
                dataset_default_cs=dataset_default_cs,
            )
        if precheck_only:
            _cleanup_uploaded_batch_files(staged_successful)
            return _build_batch_response(
                files=files,
                successful=[],
                failed=staged_failed,
                precheck_scan_run_id=str(scan_run.id) if scan_run is not None else None,
            )
        governance_profile_cache: dict[str, Any] = {}
        finalize_results = await _gather_with_concurrency_limit(
            [
                lambda staged=staged: _process_saved_batch_upload(
                    background_tasks=background_tasks,
                    db=SessionLocal(),
                    tenant_id=tenant_id,
                    account_id=account_id,
                    dataset=dataset,
                    dataset_meta=dataset_meta,
                    policy=policy,
                    pipeline_parsed=pipeline_parsed,
                    pipeline_overrides=pipeline_overrides,
                    defaults=defaults,
                    identity=UploadIdentity(
                        filename=staged["filename"],
                        file_ext=staged["file_ext"],
                        upload_key=staged["upload_key"],
                        source_path=staged["source_path"],
                    ),
                    file_id=staged["file_id"],
                    file_path=Path(staged["file_path"]),
                    file_size=staged["file_size"],
                    file_sha256=staged["file_sha256"],
                    content_type=staged["content_type"],
                    request_parser_backend=parser_backend,
                    request_chunk_strategy=chunk_strategy,
                    user_patch=_select_upload_user_patch(
                        user_meta_by_key=user_meta_by_key,
                        upload_key=staged["upload_key"],
                        filename=staged["filename"],
                    ),
                    upload_only=upload_only,
                    governance_profile_cache=governance_profile_cache,
                )
                for staged in staged_successful
            ],
            limit=max_concurrent,
        )
        successful, processed_failed = _partition_batch_results(finalize_results)
        failed = staged_failed + processed_failed
        _finalize_batch_ingestion_run(
            db=db,
            tenant_id=tenant_id,
            ingestion_run=ingestion_run,
            files=files,
            successful=successful,
            failed=failed,
        )
        return _build_batch_response(
            files=files,
            successful=successful,
            failed=failed,
            precheck_scan_run_id=str(scan_run.id) if scan_run is not None else None,
        )
    governance_profile_cache: dict[str, Any] = {}
    direct_results = await _gather_with_concurrency_limit(
        [
            lambda file=file: _process_live_batch_upload(
                background_tasks=background_tasks,
                db=SessionLocal(),
                tenant_id=tenant_id,
                account_id=account_id,
                dataset=dataset,
                dataset_meta=dataset_meta,
                policy=policy,
                pipeline_parsed=pipeline_parsed,
                pipeline_overrides=pipeline_overrides,
                defaults=defaults,
                file=file,
                user_meta_by_key=user_meta_by_key,
                request_parser_backend=parser_backend,
                request_chunk_strategy=chunk_strategy,
                upload_only=upload_only,
                governance_profile_cache=governance_profile_cache,
            )
            for file in files
        ],
        limit=max_concurrent,
    )
    successful, failed = _partition_batch_results(direct_results)
    _finalize_batch_ingestion_run(
        db=db,
        tenant_id=tenant_id,
        ingestion_run=ingestion_run,
        files=files,
        successful=successful,
        failed=failed,
    )
    return _build_batch_response(files=files, successful=successful, failed=failed)

"""Document ingestion operations for uploaded files, URLs, and local HTML."""

import contextlib
import json
import logging
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi import BackgroundTasks, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.api.schemas.document import DocumentPipelineOptions
from app.api.schemas.document_ingestion import (
    LocalHtmlIngestRequest,
    PipelineOptionOverrides,
    PipelineOverridesFormFields,
    UploadDocumentFormFields,
    UrlUploadRequest,
)
from app.api.utils.document_pipeline_input import parse_pipeline_json
from app.api.utils.upload import (
    _normalize_upload_key as normalize_upload_key,
)
from app.api.utils.upload import (
    _sanitize_filename,
    save_upload_file_with_hash,
)
from app.api.utils.upload import (
    _sanitize_filename as sanitize_filename,
)
from app.api.utils.url_ingest import validate_url_for_ingest
from app.core.config import settings
from app.models.dataset import Dataset
from app.models.document import Document as DBDocument
from app.rag.preprocessing.html_canonical import normalize_url_for_dedup
from app.services import dataset_service, document_user_metadata, ingestion_run_service
from app.services import document_ingestion_policy as ingestion_plan
from app.services import document_ingestion_sources as ingestion_sources
from app.services import document_source_persistence as source_persistence
from app.services.document_identity import (
    build_document_dedup_key,
    compute_pipeline_hash,
    get_content_sha256,
    set_content_sha256,
    sync_pipeline_execution_identity,
)
from app.services.document_index_channel_service import reconcile_document_index_channels
from app.services.document_processing_dispatch import LocalProcessingSource, dispatch_uploaded_document
from app.services.document_processing_operations import retry_document
from app.services.ingestion_policy import parse_ingestion_policy_from_metadata
from app.services.pipeline_config import upsert_pipeline_metadata
from app.storage.object.runtime import (
    document_object_storage_enabled,
    document_object_store_metadata,
    get_document_object_store,
    is_object_storage_uri,
)
from app.tasks.locks import task_job_lock_ttl_sec
from app.types.pipeline import PipelineOptions

DUPLICATE_DOCUMENT_PROCESSING_DETAIL = "Duplicate document is currently processing"
INGEST_LOCK_UNAVAILABLE_DETAIL = "Ingest lock unavailable"
logger = logging.getLogger("services.document_ingestion")


def _upload_extension_allowed(file_ext: str) -> bool:
    return file_ext in settings.allowed_extensions_list


def _document_object_storage_enabled() -> bool:
    return document_object_storage_enabled()


def _unlink_upload(path: Path) -> None:
    source_persistence.unlink_source(path)


@dataclass
class _UploadFileLease:
    path: Path | None = None
    owned: bool = False

    def acquire(self, path: Path) -> None:
        self.path = path
        self.owned = True

    def transfer(self) -> None:
        self.owned = False

    def cleanup(self) -> None:
        if self.owned and self.path is not None:
            _unlink_upload(self.path)


def _create_ingestion_run_if_missing(
    *,
    db: Session,
    tenant_id: UUID,
    dataset: Dataset,
    account_id: str,
    ingestion_run_id: UUID | None,
    ingestion_kind: str | None,
    default_kind: str,
    config: dict[str, Any],
) -> UUID | None:
    if ingestion_run_id is not None:
        return ingestion_run_id
    try:
        ingestion_kind_norm = str(ingestion_kind or default_kind).strip() or default_kind
        ingestion_run = ingestion_run_service.create_run(
            db,
            tenant_id=tenant_id,
            dataset_id=dataset.id,
            requested_by=account_id,
            kind=ingestion_kind_norm,
            config=config,
            expected_documents=1,
        )
        return ingestion_run.id
    except Exception:
        return None


def _finalize_document_metadata(
    doc_metadata: dict[str, Any],
    *,
    content_sha256: str | None,
    pipeline_options: PipelineOptions,
    ingestion_meta: dict[str, Any] | None,
    ingestion_run_id: UUID | None,
    ingestion_kind: str | None,
    default_kind: str,
    parser_backend_resolved: str | None = None,
) -> tuple[dict[str, Any], str]:
    set_content_sha256(doc_metadata, content_sha256)
    upsert_pipeline_metadata(doc_metadata, options=pipeline_options)
    if ingestion_meta:
        doc_metadata["ingestion"] = ingestion_meta

    pipeline_hash = compute_pipeline_hash(doc_metadata)
    doc_metadata["pipeline_hash"] = pipeline_hash
    doc_metadata.setdefault("active_pipeline_hash", pipeline_hash)
    doc_metadata.setdefault("active_pipeline_ready", False)
    sync_pipeline_execution_identity(
        doc_metadata,
        content_sha256=content_sha256,
        pipeline_hash=pipeline_hash,
        parser_backend_resolved=parser_backend_resolved,
    )
    if ingestion_run_id is not None:
        doc_metadata.setdefault("created_by_run_id", str(ingestion_run_id))
        doc_metadata["last_ingestion_run_id"] = str(ingestion_run_id)
        doc_metadata["last_ingestion_kind"] = str(ingestion_kind or default_kind)
    return doc_metadata, pipeline_hash


def _enforce_url_upload_quota(db: Session, *, tenant_id: UUID, additional_bytes: int, final_path: Path) -> None:
    try:
        from app.services.tenant_quota_service import enforce_tenant_upload_quotas

        enforce_tenant_upload_quotas(
            db,
            tenant_id=tenant_id,
            additional_docs=1,
            additional_bytes=additional_bytes,
        )
    except HTTPException:
        with contextlib.suppress(OSError):
            final_path.unlink(missing_ok=True)
        raise


def _create_pending_document_record(
    *,
    file_id: UUID,
    tenant_id: UUID,
    dataset: Dataset,
    filename: str,
    file_ext: str,
    file_size: int,
    file_path: str | Path,
    account_id: str,
    doc_metadata: dict[str, Any],
) -> DBDocument:
    db_document = DBDocument(
        id=file_id,
        tenant_id=tenant_id,
        dataset_id=dataset.id,
        filename=filename,
        file_type=file_ext.lstrip("."),
        file_size=file_size,
        file_path=str(file_path),
        owner_id=account_id,
        access_mode=None,
        status="pending",
        processing_progress=0,
        doc_metadata=doc_metadata,
    )
    return db_document


def _add_document_to_ingestion_run(
    *,
    db: Session,
    tenant_id: UUID,
    ingestion_run_id: UUID | None,
    db_document: DBDocument,
    source_ref: str | None,
    doc_metadata: dict[str, Any],
) -> None:
    if ingestion_run_id is None:
        return
    with contextlib.suppress(Exception):
        ingestion_run_service.add_document(
            db,
            tenant_id=tenant_id,
            run_id=ingestion_run_id,
            document_id=db_document.id,
            source_ref=source_ref,
            initial_status=str(db_document.status or "pending"),
            doc_meta=dict(doc_metadata),
        )


def _prepare_document_ingestion(
    *,
    db: Session,
    tenant_id: UUID,
    dataset: Dataset,
    filename: str,
    file_ext: str,
    requested_parser_backend: str,
    requested_chunk_strategy: str,
    pipeline: DocumentPipelineOptions | None,
    source_url: str | None,
    preserve_pdf_auto: bool,
) -> ingestion_plan.PreparedDocumentIngestion:
    ingestion_policy = ingestion_plan.resolve_document_ingestion_policy(
        db=db,
        tenant_id=tenant_id,
        dataset=dataset,
        filename=filename,
        file_ext=file_ext,
        requested_parser_backend=requested_parser_backend,
        requested_chunk_strategy=requested_chunk_strategy,
        pipeline=pipeline,
        source_url=source_url,
    )
    resolved_pipeline = ingestion_plan.resolve_document_pipeline(
        file_ext=file_ext,
        parser_backend_choice=ingestion_policy.parser_backend_choice,
        chunk_strategy_choice=ingestion_policy.chunk_strategy_choice,
        preserve_pdf_auto=preserve_pdf_auto,
    )
    ingestion_plan.validate_pipeline_for_strategy(
        dataset_meta=dataset.dataset_metadata,
        pipeline_options=ingestion_policy.pipeline_options,
        resolved_chunk_strategy=resolved_pipeline.chunk_strategy,
    )
    return ingestion_plan.PreparedDocumentIngestion(policy=ingestion_policy, pipeline=resolved_pipeline)


def _create_url_ingestion_run(
    *,
    db: Session,
    tenant_id: UUID,
    dataset: Dataset,
    account_id: str,
    ingestion_run_id: UUID | None,
    ingestion_kind: str | None,
    body: UrlUploadRequest,
    url: str,
    source: ingestion_sources.UrlSourceMetadata,
    pipeline: ingestion_plan.ResolvedDocumentPipeline,
) -> UUID | None:
    run_cfg = {
        "source_url": url,
        "url_final_url": source.final_url or None,
        "url_canonical_url": source.canonical_url,
        "parser_backend_requested": str(body.parser_backend or "")[:80],
        "chunk_strategy_requested": str(body.chunk_strategy or "")[:80],
        "parser_backend": str(pipeline.parser_backend or "")[:80],
        "chunk_strategy": str(pipeline.chunk_strategy or "")[:80],
    }
    return _create_ingestion_run_if_missing(
        db=db,
        tenant_id=tenant_id,
        dataset=dataset,
        account_id=account_id,
        ingestion_run_id=ingestion_run_id,
        ingestion_kind=ingestion_kind,
        default_kind="upload_url",
        config=run_cfg,
    )


def _create_local_html_ingestion_run(
    *,
    db: Session,
    tenant_id: UUID,
    dataset: Dataset,
    account_id: str,
    ingestion_run_id: UUID | None,
    ingestion_kind: str | None,
    body: LocalHtmlIngestRequest,
    source_url: str | None,
    content_type: str,
    pipeline: ingestion_plan.ResolvedDocumentPipeline,
) -> UUID | None:
    run_cfg = {
        "source_url": source_url,
        "content_type": content_type,
        "parser_backend_requested": str(body.parser_backend or "")[:80],
        "chunk_strategy_requested": str(body.chunk_strategy or "")[:80],
        "parser_backend": str(pipeline.parser_backend or "")[:80],
        "chunk_strategy": str(pipeline.chunk_strategy or "")[:80],
    }
    return _create_ingestion_run_if_missing(
        db=db,
        tenant_id=tenant_id,
        dataset=dataset,
        account_id=account_id,
        ingestion_run_id=ingestion_run_id,
        ingestion_kind=ingestion_kind,
        default_kind="connector_html",
        config=run_cfg,
    )


def _build_url_document_metadata(
    *,
    body: UrlUploadRequest,
    url: str,
    ingest_file: ingestion_sources.UrlIngestFile,
    source: ingestion_sources.UrlSourceMetadata,
    pipeline: ingestion_plan.ResolvedDocumentPipeline,
) -> dict[str, Any]:
    requested_parser_backend = str(body.parser_backend or "").strip().lower()
    parser_backend_resolved = (
        None
        if pipeline.parser_backend == "auto" and requested_parser_backend in {"", "auto"}
        else pipeline.parser_backend
    )
    return {
        "parser_backend": pipeline.parser_backend,
        "parser_backend_requested": str(body.parser_backend or "").lower(),
        "parser_backend_resolved": parser_backend_resolved,
        "chunk_strategy": pipeline.chunk_strategy,
        "chunk_strategy_requested": str(body.chunk_strategy or "").lower(),
        "source_url": url,
        "source_fetched_at": ingest_file.fetched_at_iso,
        "source_last_modified_at": source.last_modified_at,
        "source_last_modified_source": source.last_modified_source,
        "source_last_modified_raw": source.last_modified_raw,
        "source_etag": source.etag,
        "url_content_type": ingest_file.content_type or None,
        "url_final_url": source.final_url or None,
        "url_canonical_url": source.canonical_url,
        "url_normalized_url": source.normalized_url or None,
        "url_normalized_requested": source.normalized_requested or None,
        "url_normalized_final": source.normalized_final or None,
        "url_normalized_canonical": source.normalized_canonical,
    }


def _build_local_html_document_metadata(
    *,
    body: LocalHtmlIngestRequest,
    source_url: str | None,
    url_normalized: str | None,
    fetched_at_iso: str,
    content_type: str,
    pipeline: ingestion_plan.ResolvedDocumentPipeline,
) -> dict[str, Any]:
    requested_parser_backend = str(body.parser_backend or "").strip().lower()
    parser_backend_resolved = (
        None
        if pipeline.parser_backend == "auto" and requested_parser_backend in {"", "auto"}
        else pipeline.parser_backend
    )
    return {
        "parser_backend": pipeline.parser_backend,
        "parser_backend_requested": str(body.parser_backend or "").lower(),
        "parser_backend_resolved": parser_backend_resolved,
        "chunk_strategy": pipeline.chunk_strategy,
        "chunk_strategy_requested": str(body.chunk_strategy or "").lower(),
        "source_url": source_url,
        "source_fetched_at": fetched_at_iso,
        "source_last_modified_at": fetched_at_iso,
        "source_last_modified_source": "fallback:fetched_at",
        "source_last_modified_raw": None,
        "source_etag": None,
        "url_content_type": content_type,
        "url_final_url": source_url,
        "url_normalized_url": url_normalized or None,
    }


async def _persist_and_process_ingested_document(
    *,
    db: Session,
    background_tasks: BackgroundTasks | None,
    tenant_id: UUID,
    account_id: str,
    dataset: Dataset,
    file_id: UUID,
    filename: str,
    file_ext: str,
    file_size: int,
    file_path: str | Path,
    processing_file_path: Path,
    source_ref: str | None,
    doc_metadata: dict[str, Any],
    pipeline_hash: str,
    pipeline: ingestion_plan.ResolvedDocumentPipeline,
    ingestion_run_id: UUID | None,
) -> DBDocument:
    db_document = _create_pending_document_record(
        file_id=file_id,
        tenant_id=tenant_id,
        dataset=dataset,
        filename=filename,
        file_ext=file_ext,
        file_size=file_size,
        file_path=file_path,
        account_id=account_id,
        doc_metadata=doc_metadata,
    )
    if settings.UPLOAD_DEDUP_ENABLED:
        db_document.dedup_key = build_document_dedup_key(
            content_sha256=get_content_sha256(doc_metadata),
            pipeline_hash=pipeline_hash,
        )
    keep_local_processing_file = False
    await source_persistence.persist_uploaded_document(db, db_document, file_path=processing_file_path)

    with contextlib.suppress(Exception):
        reconcile_document_index_channels(
            db,
            document=db_document,
            pipeline_hash=pipeline_hash,
            reset_enabled_to_pending=True,
            commit=True,
        )

    _add_document_to_ingestion_run(
        db=db,
        tenant_id=tenant_id,
        ingestion_run_id=ingestion_run_id,
        db_document=db_document,
        source_ref=source_ref,
        doc_metadata=doc_metadata,
    )
    try:
        keep_local_processing_file = await dispatch_uploaded_document(
            db=db,
            background_tasks=background_tasks,
            tenant_id=tenant_id,
            source=LocalProcessingSource(processing_file_path),
            requested_by=account_id,
            pipeline_hash=pipeline_hash,
            parser_backend=pipeline.parser_backend,
            chunk_strategy=pipeline.chunk_strategy,
            document=db_document,
        )
    finally:
        if is_object_storage_uri(str(file_path)) and not keep_local_processing_file:
            source_persistence.unlink_source(processing_file_path)
    return db_document


async def _reuse_duplicate_document_for_ingest(
    *,
    background_tasks: BackgroundTasks | None,
    db: Session,
    tenant_id: UUID,
    account_id: str,
    duplicate: DBDocument,
    content_sha256: str,
    pipeline_hash: str,
) -> DBDocument:
    status0 = str(duplicate.status or "").strip().lower()
    if status0 in {"pending", "processing"}:
        if source_persistence.document_matches_dedup_identity(
            duplicate, file_sha256=content_sha256, pipeline_hash=pipeline_hash
        ):
            return duplicate
        raise HTTPException(status_code=409, detail=DUPLICATE_DOCUMENT_PROCESSING_DETAIL)

    meta = dict(duplicate.doc_metadata or {})
    sync_pipeline_execution_identity(
        meta,
        content_sha256=content_sha256,
        pipeline_hash=pipeline_hash,
        parser_backend_resolved=str(meta.get("parser_backend_resolved") or "").strip() or None,
    )
    duplicate.doc_metadata = meta
    duplicate.dedup_key = build_document_dedup_key(content_sha256=content_sha256, pipeline_hash=pipeline_hash)
    db.commit()
    db.refresh(duplicate)

    if status0 == "failed":
        if background_tasks is None:
            raise HTTPException(status_code=409, detail="Failed duplicate requires retry scheduling context")
        await retry_document(
            document_id=duplicate.id,
            background_tasks=background_tasks,
            force=True,
            skip_if_unchanged=True,
            tenant_id=tenant_id,
            account_id=account_id,
            db=db,
        )
        db.refresh(duplicate)
    return duplicate


async def ingest_url(
    *,
    background_tasks: BackgroundTasks | None,
    body: UrlUploadRequest,
    tenant_id: UUID,
    account_id: str,
    db: Session,
    ingestion_run_id: UUID | None = None,
    ingestion_kind: str | None = None,
) -> DBDocument:
    """
    Shared implementation for URL ingestion.

    - Used by API endpoint and connector runs.
    - If task queue is disabled and `background_tasks` is None, processing runs inline (async).
    """
    if not settings.URL_INGEST_ENABLED:
        raise HTTPException(status_code=400, detail="URL ingestion is disabled")

    url = await validate_url_for_ingest(str(body.url or ""))
    dataset = dataset_service.resolve_writable_dataset(db, tenant_id, account_id, body.dataset_id)
    ingest_file = await ingestion_sources.download_url_ingest_file(url=url, body=body, tenant_id=tenant_id)
    source_lease = source_persistence.SourceFileLease(ingest_file.final_path)
    try:
        return await _ingest_url_upload_request_with_source(
            background_tasks=background_tasks,
            body=body,
            tenant_id=tenant_id,
            account_id=account_id,
            db=db,
            ingestion_run_id=ingestion_run_id,
            ingestion_kind=ingestion_kind,
            ingest_file=ingest_file,
            url=url,
            dataset=dataset,
            source_lease=source_lease,
        )
    finally:
        await source_lease.cleanup_source()


async def _ingest_url_upload_request_with_source(
    *,
    background_tasks: BackgroundTasks | None,
    body: UrlUploadRequest,
    tenant_id: UUID,
    account_id: str,
    db: Session,
    ingestion_run_id: UUID | None,
    ingestion_kind: str | None,
    ingest_file: ingestion_sources.UrlIngestFile,
    url: str,
    dataset: Dataset,
    source_lease: source_persistence.SourceFileLease,
) -> DBDocument:
    source = await ingestion_sources.url_source_metadata(url=url, ingest_file=ingest_file)
    safe_name = _sanitize_filename(body.filename or Path(ingest_file.final_path).name)
    prepared = _prepare_document_ingestion(
        db=db,
        tenant_id=tenant_id,
        dataset=dataset,
        filename=safe_name,
        file_ext=ingest_file.file_ext,
        requested_parser_backend=body.parser_backend,
        requested_chunk_strategy=body.chunk_strategy,
        pipeline=body.pipeline,
        source_url=url,
        preserve_pdf_auto=True,
    )
    ingestion_run_id = _create_url_ingestion_run(
        db=db,
        tenant_id=tenant_id,
        dataset=dataset,
        account_id=account_id,
        ingestion_run_id=ingestion_run_id,
        ingestion_kind=ingestion_kind,
        body=body,
        url=url,
        source=source,
        pipeline=prepared.pipeline,
    )

    doc_metadata = _build_url_document_metadata(
        body=body,
        url=url,
        ingest_file=ingest_file,
        source=source,
        pipeline=prepared.pipeline,
    )
    doc_metadata, pipeline_hash = _finalize_document_metadata(
        doc_metadata,
        content_sha256=ingest_file.content_sha256,
        pipeline_options=prepared.policy.pipeline_options,
        ingestion_meta=prepared.policy.ingestion_meta,
        ingestion_run_id=ingestion_run_id,
        ingestion_kind=ingestion_kind,
        default_kind="upload_url",
        parser_backend_resolved=str(doc_metadata.get("parser_backend_resolved") or "").strip() or None,
    )

    if settings.UPLOAD_DEDUP_ENABLED and ingest_file.content_sha256:
        duplicate = source_persistence.find_duplicate_document(
            db,
            tenant_id=tenant_id,
            dataset_id=dataset.id,
            file_sha256=ingest_file.content_sha256,
            pipeline_hash=pipeline_hash,
        )
        if duplicate is not None:
            with contextlib.suppress(OSError):
                ingest_file.final_path.unlink(missing_ok=True)
            return await _reuse_duplicate_document_for_ingest(
                background_tasks=background_tasks,
                db=db,
                tenant_id=tenant_id,
                account_id=account_id,
                duplicate=duplicate,
                content_sha256=ingest_file.content_sha256,
                pipeline_hash=pipeline_hash,
            )

    file_size = int(ingest_file.downloaded.size_bytes)
    _enforce_url_upload_quota(db, tenant_id=tenant_id, additional_bytes=file_size, final_path=ingest_file.final_path)
    stored_path = await source_persistence.store_document_source(
        file_path=ingest_file.final_path,
        tenant_id=tenant_id,
        dataset_id=dataset.id,
        document_id=ingest_file.file_id,
        extension=ingest_file.file_ext,
        content_type=ingest_file.content_type or None,
    )
    if is_object_storage_uri(stored_path):
        store = get_document_object_store()
        if store is not None:
            doc_metadata.update(document_object_store_metadata(store))

    source_lease.transfer()
    try:
        return await _persist_and_process_ingested_document(
            db=db,
            background_tasks=background_tasks,
            tenant_id=tenant_id,
            account_id=account_id,
            dataset=dataset,
            file_id=ingest_file.file_id,
            filename=safe_name,
            file_ext=ingest_file.file_ext,
            file_size=file_size,
            file_path=stored_path,
            processing_file_path=ingest_file.final_path,
            source_ref=url,
            doc_metadata=doc_metadata,
            pipeline_hash=pipeline_hash,
            pipeline=prepared.pipeline,
            ingestion_run_id=ingestion_run_id,
        )
    except source_persistence.DuplicatePersistedDocumentError as exc:
        return await _reuse_duplicate_document_for_ingest(
            background_tasks=background_tasks,
            db=db,
            tenant_id=tenant_id,
            account_id=account_id,
            duplicate=exc.document,
            content_sha256=ingest_file.content_sha256,
            pipeline_hash=pipeline_hash,
        )


async def ingest_file(
    *,
    background_tasks: BackgroundTasks,
    file: UploadFile,
    form: UploadDocumentFormFields,
    overrides_form: PipelineOverridesFormFields,
    tenant_id: UUID,
    account_id: str,
    db: Session,
) -> DBDocument:
    lease = _UploadFileLease()
    try:
        return await _ingest_file_impl(
            background_tasks,
            file,
            form,
            overrides_form,
            tenant_id=tenant_id,
            account_id=account_id,
            db=db,
            file_lease=lease,
        )
    finally:
        lease.cleanup()


@dataclass
class _IngestLockLease:
    redis: Any = None
    key: str | None = None
    value: str | None = None
    retained: bool = False

    def acquire(self, *, redis: Any, key: str, value: str) -> None:
        self.redis = redis
        self.key = key
        self.value = value

    def retain(self) -> None:
        self.retained = True

    async def cleanup(self) -> None:
        if self.retained or self.redis is None or not self.key or not self.value:
            return
        from app.tasks.locks import release_lock

        await release_lock(self.redis, key=self.key, value=self.value)


def _document_upload_path(tenant_id: UUID, document_id: UUID, extension: str) -> Path:
    upload_dir = Path(settings.UPLOAD_DIR) / str(tenant_id)
    if _document_object_storage_enabled():
        upload_dir /= ".tmp"
    upload_dir.mkdir(parents=True, exist_ok=True)
    return upload_dir / f"{document_id}{extension}"


async def _maybe_acquire_ingest_lock(
    *,
    tenant_id: UUID,
    dataset_id: UUID | None,
    file_sha256: str | None,
    pipeline_hash: str | None,
    account_id: str,
    doc_metadata: dict[str, Any],
    ingest_lock: _IngestLockLease,
) -> None:
    if not file_sha256 or not pipeline_hash or dataset_id is None:
        return
    if not settings.UPLOAD_DEDUP_ENABLED:
        return
    if not settings.TASK_QUEUE_ENABLED:
        return
    try:
        from app.tasks.locks import acquire_lock, make_lock_value
        from app.tasks.queue import get_queue

        redis = await get_queue()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Ingest lock queue unavailable: %s", str(exc)[:200])
        raise HTTPException(status_code=503, detail=INGEST_LOCK_UNAVAILABLE_DETAIL) from exc

    if redis is None:
        raise HTTPException(status_code=503, detail=INGEST_LOCK_UNAVAILABLE_DETAIL)

    ingest_lock_key = f"lock:ingest:{tenant_id}:{dataset_id}:{file_sha256}:{pipeline_hash}"
    ingest_lock_value = make_lock_value(account_id)
    try:
        acquired = await acquire_lock(
            redis,
            key=ingest_lock_key,
            value=ingest_lock_value,
            ttl_sec=task_job_lock_ttl_sec(),
            fail_open=False,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Ingest lock acquire failed: %s", str(exc)[:200])
        raise HTTPException(status_code=503, detail=INGEST_LOCK_UNAVAILABLE_DETAIL) from exc
    if not acquired:
        # A same-key request is already between hash calculation and persistence.
        # Continue as an idempotent follower: the document lookup or the database
        # uniqueness constraint below will return the winner's document.
        logger.info(
            "Ingest lock follower tenant_id=%s dataset_id=%s; deferring to database dedup",
            str(tenant_id),
            str(dataset_id),
        )
        return

    doc_metadata["ingest_lock_key"] = ingest_lock_key
    doc_metadata["ingest_lock_value"] = ingest_lock_value
    ingest_lock.acquire(redis=redis, key=ingest_lock_key, value=ingest_lock_value)


def _retain_ingest_lock_if_task_handed_off(document: DBDocument, *, ingest_lock: _IngestLockLease) -> None:
    if str((document.doc_metadata or {}).get("task_id") or "").strip():
        ingest_lock.retain()


def _sync_duplicate_document_pipeline_identity(
    duplicate_document: DBDocument,
    *,
    doc_metadata: dict[str, Any],
    file_sha256: str,
    pipeline_hash: str,
) -> None:
    sync_pipeline_execution_identity(
        doc_metadata,
        content_sha256=file_sha256,
        pipeline_hash=pipeline_hash,
        parser_backend_resolved=str(doc_metadata.get("parser_backend_resolved") or "").strip() or None,
    )
    normalized_pipeline_hash = str(pipeline_hash or "").strip()
    if not normalized_pipeline_hash:
        normalized_pipeline_hash = None
    doc_metadata["pipeline_hash"] = normalized_pipeline_hash
    duplicate_document.dedup_key = build_document_dedup_key(content_sha256=file_sha256, pipeline_hash=pipeline_hash)


async def _retry_failed_persisted_duplicate(
    document: DBDocument,
    *,
    background_tasks: BackgroundTasks,
    tenant_id: UUID,
    account_id: str,
    db: Session,
) -> None:
    if str(document.status or "").lower() != "failed":
        return

    await retry_document(
        document_id=document.id,
        background_tasks=background_tasks,
        force=True,
        skip_if_unchanged=True,
        tenant_id=tenant_id,
        account_id=account_id,
        db=db,
    )
    with contextlib.suppress(Exception):
        db.refresh(document)


@dataclass(frozen=True)
class _UploadIdentity:
    filename: str
    file_ext: str
    upload_key: str
    source_path: str | None


@dataclass(frozen=True)
class _PreparedDocumentMetadata:
    doc_metadata: dict[str, Any]
    pipeline_hash: str


def _normalize_upload_identity(file: UploadFile) -> _UploadIdentity:

    raw_filename = file.filename
    upload_key = normalize_upload_key(raw_filename)
    source_path = upload_key if "/" in upload_key else None
    file.filename = sanitize_filename(raw_filename)
    return _UploadIdentity(
        filename=str(file.filename or ""),
        file_ext=Path(str(file.filename or "")).suffix.lower(),
        upload_key=upload_key,
        source_path=source_path,
    )


def _require_upload_extension(file_ext: str) -> None:
    if not _upload_extension_allowed(file_ext):
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type. Allowed: {settings.allowed_extensions_list}",
        )


def _parse_single_user_metadata(user_metadata: str | None) -> dict[str, Any] | None:
    if not isinstance(user_metadata, str) or not user_metadata.strip():
        return None
    raw = user_metadata.strip()
    max_len = settings.USER_METADATA_FORM_JSON_MAX_CHARS
    if max_len > 0 and len(raw) > max_len:
        raise HTTPException(status_code=400, detail="user_metadata is too large")
    try:
        obj = json.loads(raw)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail="Invalid user_metadata JSON (expect UTF-8)") from exc
    if not isinstance(obj, dict):
        raise HTTPException(status_code=400, detail="user_metadata must be a JSON object")
    return obj


def _build_document_metadata(
    *,
    identity: _UploadIdentity,
    request_parser_backend: str,
    request_chunk_strategy: str,
    resolved_pipeline: ingestion_plan.ResolvedUploadPipeline,
    file_sha256: str | None,
    user_patch: dict[str, Any] | None,
    upload_only: bool,
) -> _PreparedDocumentMetadata:

    requested_parser_backend = (request_parser_backend or "").strip().lower()
    doc_metadata = {
        "parser_backend": resolved_pipeline.resolved_parser_backend,
        "parser_backend_requested": requested_parser_backend,
        "parser_backend_resolved": (
            None
            if identity.file_ext == ".pdf" and requested_parser_backend in {"", "auto"}
            else resolved_pipeline.resolved_parser_backend
        ),
        "chunk_strategy": resolved_pipeline.resolved_chunk_strategy,
        "chunk_strategy_requested": (request_chunk_strategy or "").lower(),
    }
    if identity.source_path:
        doc_metadata["source_path"] = identity.source_path
    if isinstance(file_sha256, str) and file_sha256:
        set_content_sha256(doc_metadata, file_sha256)
    upsert_pipeline_metadata(doc_metadata, options=resolved_pipeline.pipeline_options)
    if resolved_pipeline.ingestion_meta:
        doc_metadata["ingestion"] = resolved_pipeline.ingestion_meta
    if isinstance(user_patch, dict) and user_patch:
        doc_metadata["user"] = document_user_metadata.apply_user_metadata_patch(
            current={},
            patch=user_patch,
            replace=True,
        )
    if upload_only:
        doc_metadata["ingest_stage"] = "uploaded_only"
    pipeline_hash = compute_pipeline_hash(doc_metadata)
    doc_metadata["pipeline_hash"] = pipeline_hash
    doc_metadata.setdefault("active_pipeline_hash", pipeline_hash)
    doc_metadata.setdefault("active_pipeline_ready", False)
    sync_pipeline_execution_identity(
        doc_metadata,
        content_sha256=file_sha256 if isinstance(file_sha256, str) else None,
        pipeline_hash=pipeline_hash,
        parser_backend_resolved=str(doc_metadata.get("parser_backend_resolved") or "").strip() or None,
    )
    return _PreparedDocumentMetadata(doc_metadata=doc_metadata, pipeline_hash=pipeline_hash)


def _merge_duplicate_document_metadata(
    duplicate_document: DBDocument,
    *,
    identity: _UploadIdentity,
    request_parser_backend: str,
    request_chunk_strategy: str,
    resolved_pipeline: ingestion_plan.ResolvedUploadPipeline,
    pipeline_hash: str,
    file_sha256: str,
    user_patch: dict[str, Any] | None,
    ingest_lock: _IngestLockLease,
) -> dict[str, Any]:

    meta_any = dict(duplicate_document.doc_metadata or {})
    requested_parser_backend = (request_parser_backend or "").strip().lower()
    meta_any["parser_backend"] = resolved_pipeline.resolved_parser_backend
    meta_any["parser_backend_requested"] = requested_parser_backend
    meta_any["parser_backend_resolved"] = (
        None
        if identity.file_ext == ".pdf" and requested_parser_backend in {"", "auto"}
        else resolved_pipeline.resolved_parser_backend
    )
    meta_any["chunk_strategy"] = resolved_pipeline.resolved_chunk_strategy
    meta_any["chunk_strategy_requested"] = (request_chunk_strategy or "").lower()
    if identity.source_path and not meta_any.get("source_path"):
        meta_any["source_path"] = identity.source_path
    _sync_duplicate_document_pipeline_identity(
        duplicate_document,
        doc_metadata=meta_any,
        file_sha256=file_sha256,
        pipeline_hash=pipeline_hash,
    )
    upsert_pipeline_metadata(meta_any, options=resolved_pipeline.pipeline_options)
    if resolved_pipeline.ingestion_meta:
        meta_any["ingestion"] = resolved_pipeline.ingestion_meta
    if isinstance(user_patch, dict) and user_patch:
        current_user = meta_any.get("user") if isinstance(meta_any.get("user"), dict) else {}
        meta_any["user"] = document_user_metadata.apply_user_metadata_patch(
            current=current_user,
            patch=user_patch,
            replace=False,
        )
    active_pipeline_hash = str(meta_any.get("pipeline_hash") or "").strip()
    if not active_pipeline_hash:
        active_pipeline_hash = None
    meta_any.setdefault("active_pipeline_hash", active_pipeline_hash)
    meta_any.setdefault("active_pipeline_ready", bool(str(duplicate_document.status or "").lower() == "completed"))
    sync_pipeline_execution_identity(
        meta_any,
        content_sha256=file_sha256,
        pipeline_hash=pipeline_hash,
        parser_backend_resolved=str(meta_any.get("parser_backend_resolved") or "").strip() or None,
    )
    if ingest_lock.key and ingest_lock.value:
        meta_any["ingest_lock_key"] = ingest_lock.key
        meta_any["ingest_lock_value"] = ingest_lock.value
    return meta_any


async def _reuse_duplicate_document(
    duplicate_document: DBDocument,
    *,
    db: Session,
    identity: _UploadIdentity,
    request_parser_backend: str,
    request_chunk_strategy: str,
    resolved_pipeline: ingestion_plan.ResolvedUploadPipeline,
    pipeline_hash: str,
    file_sha256: str,
    user_patch: dict[str, Any] | None,
    upload_only: bool,
    background_tasks: BackgroundTasks,
    tenant_id: UUID,
    account_id: str,
    ingest_lock: _IngestLockLease,
) -> DBDocument:
    status0 = str(duplicate_document.status or "").lower()
    if status0 in {"pending", "processing"}:
        if source_persistence.document_matches_dedup_identity(
            duplicate_document,
            file_sha256=file_sha256,
            pipeline_hash=pipeline_hash,
        ):
            return duplicate_document

        raise HTTPException(status_code=409, detail=DUPLICATE_DOCUMENT_PROCESSING_DETAIL)
    duplicate_document.doc_metadata = _merge_duplicate_document_metadata(
        duplicate_document,
        identity=identity,
        request_parser_backend=request_parser_backend,
        request_chunk_strategy=request_chunk_strategy,
        resolved_pipeline=resolved_pipeline,
        pipeline_hash=pipeline_hash,
        file_sha256=file_sha256,
        user_patch=user_patch,
        ingest_lock=ingest_lock,
    )
    db.commit()
    db.refresh(duplicate_document)
    if upload_only:
        return duplicate_document

    await retry_document(
        document_id=duplicate_document.id,
        background_tasks=background_tasks,
        force=True,
        skip_if_unchanged=True,
        tenant_id=tenant_id,
        account_id=account_id,
        db=db,
    )
    db.refresh(duplicate_document)
    _retain_ingest_lock_if_task_handed_off(duplicate_document, ingest_lock=ingest_lock)
    return duplicate_document


def _create_single_ingestion_run(
    *,
    db: Session,
    tenant_id: UUID,
    dataset_id: UUID | None,
    account_id: str,
    identity: _UploadIdentity,
    parser_backend: str,
    chunk_strategy: str,
    resolved_pipeline: ingestion_plan.ResolvedUploadPipeline,
    pipeline_hash: str,
    pipeline_parsed: Any,
) -> Any:
    try:
        return ingestion_run_service.create_run(
            db,
            tenant_id=tenant_id,
            dataset_id=dataset_id,
            requested_by=account_id,
            kind="upload",
            config={
                "filename": str(identity.filename or "")[:255],
                "source_path": (str(identity.source_path)[:1000] if identity.source_path else None),
                "file_ext": str(identity.file_ext or "")[:16],
                "parser_backend_requested": str(parser_backend or "")[:80],
                "chunk_strategy_requested": str(chunk_strategy or "")[:80],
                "parser_backend": str(resolved_pipeline.resolved_parser_backend or "")[:80],
                "chunk_strategy": str(resolved_pipeline.resolved_chunk_strategy or "")[:80],
                "pipeline_hash": str(pipeline_hash or "")[:64],
                "ingestion_meta": dict(resolved_pipeline.ingestion_meta or {}),
                "pipeline": (pipeline_parsed.model_dump(exclude_none=True) if pipeline_parsed is not None else None),
            },
            expected_documents=1,
        )
    except Exception:
        return None


def _attach_document_to_ingestion_run(
    *,
    db: Session,
    ingestion_run: Any,
    tenant_id: UUID,
    identity: _UploadIdentity,
    document: Any,
    created: bool,
) -> None:
    if ingestion_run is None or document is None:
        return
    try:
        meta0 = dict(document.doc_metadata or {})
        if created and not meta0.get("created_by_run_id"):
            meta0["created_by_run_id"] = str(ingestion_run.id)
        meta0["last_ingestion_run_id"] = str(ingestion_run.id)
        meta0["last_ingestion_kind"] = "upload"
        document.doc_metadata = meta0
        db.commit()
        db.refresh(document)
    except Exception:
        meta0 = dict(document.doc_metadata or {})
    with contextlib.suppress(Exception):
        ingestion_run_service.add_document(
            db,
            tenant_id=tenant_id,
            run_id=ingestion_run.id,
            document_id=document.id,
            source_ref=(identity.source_path or document.filename),
            initial_status=str(document.status or "created"),
            doc_meta=meta0,
        )


async def _maybe_resolve_single_upload_duplicate(
    *,
    db: Session,
    background_tasks: BackgroundTasks,
    tenant_id: UUID,
    account_id: str,
    dataset_id: UUID | None,
    identity: _UploadIdentity,
    request_parser_backend: str,
    request_chunk_strategy: str,
    resolved_pipeline: ingestion_plan.ResolvedUploadPipeline,
    pipeline_hash: str,
    file_sha256: str | None,
    user_patch: dict[str, Any] | None,
    ingest_lock: _IngestLockLease,
) -> Any | None:
    if not settings.UPLOAD_DEDUP_ENABLED or not isinstance(file_sha256, str) or not file_sha256:
        return None
    duplicate = source_persistence.find_duplicate_document(
        db,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        file_sha256=file_sha256,
        pipeline_hash=pipeline_hash,
    )
    if duplicate is not None and str(duplicate.status or "").lower() not in {"failed"}:
        logger.info(
            "Upload dedup hit tenant_id=%s dataset_id=%s document_id=%s",
            str(tenant_id),
            str(dataset_id),
            str(duplicate.id),
        )
        return duplicate
    duplicate_by_sha = source_persistence.find_duplicate_document_by_sha(
        db,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        file_sha256=file_sha256,
    )
    if duplicate_by_sha is None:
        return None
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
        upload_only=False,
        background_tasks=background_tasks,
        tenant_id=tenant_id,
        account_id=account_id,
        ingest_lock=ingest_lock,
    )


async def _ingest_file_impl(
    background_tasks: BackgroundTasks,
    file: UploadFile,
    form: UploadDocumentFormFields,
    overrides_form: PipelineOverridesFormFields,
    *,
    tenant_id: UUID,
    account_id: str,
    db: Session,
    file_lease: _UploadFileLease,
):

    ingest_lock = _IngestLockLease()
    identity = _normalize_upload_identity(file)
    _require_upload_extension(identity.file_ext)
    parser_backend = form.parser_backend
    chunk_strategy = form.chunk_strategy
    dataset = dataset_service.resolve_writable_dataset(db, tenant_id, account_id, form.dataset_id)
    dataset_meta = (dataset.dataset_metadata or {}) if dataset is not None else {}
    policy = parse_ingestion_policy_from_metadata(dataset_meta if isinstance(dataset_meta, dict) else {})  # type: ignore[arg-type]
    pipeline_parsed = parse_pipeline_json(form.pipeline)
    pipeline_overrides = PipelineOptionOverrides(**asdict(overrides_form))
    dataset_default_pb, dataset_default_cs = ingestion_plan.dataset_upload_defaults(dataset_meta)
    defaults = ingestion_plan.select_upload_defaults(
        parser_backend=parser_backend,
        chunk_strategy=chunk_strategy,
        dataset_default_pb=dataset_default_pb,
        dataset_default_cs=dataset_default_cs,
    )
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
    )
    file_id = uuid.uuid4()
    file_path = _document_upload_path(tenant_id, file_id, identity.file_ext)
    file_lease.acquire(file_path)

    file_size, file_sha256 = await save_upload_file_with_hash(file, file_path, max_bytes=settings.MAX_FILE_SIZE)

    from app.services.tenant_quota_service import enforce_tenant_upload_quotas

    enforce_tenant_upload_quotas(
        db,
        tenant_id=tenant_id,
        additional_docs=1,
        additional_bytes=file_size,
    )
    user_patch = _parse_single_user_metadata(form.user_metadata)
    prepared_metadata = _build_document_metadata(
        identity=identity,
        request_parser_backend=parser_backend,
        request_chunk_strategy=chunk_strategy,
        resolved_pipeline=resolved_pipeline,
        file_sha256=file_sha256,
        user_patch=user_patch,
        upload_only=False,
    )
    doc_metadata = prepared_metadata.doc_metadata
    pipeline_hash = prepared_metadata.pipeline_hash

    await _maybe_acquire_ingest_lock(
        tenant_id=tenant_id,
        dataset_id=dataset.id if dataset is not None else None,
        file_sha256=file_sha256,
        pipeline_hash=pipeline_hash,
        account_id=account_id,
        doc_metadata=doc_metadata,
        ingest_lock=ingest_lock,
    )

    try:
        ingestion_run = _create_single_ingestion_run(
            db=db,
            tenant_id=tenant_id,
            dataset_id=dataset.id if dataset is not None else None,
            account_id=account_id,
            identity=identity,
            parser_backend=parser_backend,
            chunk_strategy=chunk_strategy,
            resolved_pipeline=resolved_pipeline,
            pipeline_hash=pipeline_hash,
            pipeline_parsed=pipeline_parsed,
        )
        duplicate = await _maybe_resolve_single_upload_duplicate(
            db=db,
            background_tasks=background_tasks,
            tenant_id=tenant_id,
            account_id=account_id,
            dataset_id=dataset.id if dataset is not None else None,
            identity=identity,
            request_parser_backend=parser_backend,
            request_chunk_strategy=chunk_strategy,
            resolved_pipeline=resolved_pipeline,
            pipeline_hash=pipeline_hash,
            file_sha256=file_sha256,
            user_patch=user_patch,
            ingest_lock=ingest_lock,
        )
        if duplicate is not None:
            with contextlib.suppress(Exception):
                _attach_document_to_ingestion_run(
                    db=db,
                    ingestion_run=ingestion_run,
                    tenant_id=tenant_id,
                    identity=identity,
                    document=duplicate,
                    created=False,
                )
            return duplicate

        stored_path = await source_persistence.store_document_source(
            file_path=file_path,
            tenant_id=tenant_id,
            dataset_id=dataset.id,
            document_id=file_id,
            extension=identity.file_ext,
            content_type=(file.content_type or "application/octet-stream"),
        )
        if is_object_storage_uri(stored_path):
            store = get_document_object_store()
            if store is not None:
                doc_metadata.update(document_object_store_metadata(store))
        persistence_started = False
        try:
            db_document = DBDocument(
                id=file_id,
                tenant_id=tenant_id,
                dataset_id=dataset.id,
                filename=file.filename,
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
                db_document.dedup_key = build_document_dedup_key(
                    content_sha256=file_sha256, pipeline_hash=pipeline_hash
                )
            persistence_started = True
            file_lease.transfer()
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
            with contextlib.suppress(Exception):
                _attach_document_to_ingestion_run(
                    db=db,
                    ingestion_run=ingestion_run,
                    tenant_id=tenant_id,
                    identity=identity,
                    document=exc.document,
                    created=False,
                )
            return exc.document
        except Exception:
            if not persistence_started:
                await source_persistence.cleanup_unpersisted_source(stored_path, document_metadata=doc_metadata)
            raise
        with contextlib.suppress(Exception):
            _attach_document_to_ingestion_run(
                db=db,
                ingestion_run=ingestion_run,
                tenant_id=tenant_id,
                identity=identity,
                document=db_document,
                created=True,
            )
        with contextlib.suppress(Exception):
            reconcile_document_index_channels(
                db,
                document=db_document,
                pipeline_hash=pipeline_hash,
                reset_enabled_to_pending=True,
                commit=True,
            )
        if not is_object_storage_uri(str(stored_path)):
            file_lease.transfer()

        keep_local_file = await dispatch_uploaded_document(
            background_tasks=background_tasks,
            source=LocalProcessingSource(file_path),
            tenant_id=tenant_id,
            requested_by=account_id,
            pipeline_hash=pipeline_hash,
            parser_backend=resolved_pipeline.resolved_parser_backend,
            chunk_strategy=resolved_pipeline.resolved_chunk_strategy,
            db=db,
            document=db_document,
        )
        if keep_local_file:
            file_lease.transfer()
        _retain_ingest_lock_if_task_handed_off(db_document, ingest_lock=ingest_lock)

        return db_document
    finally:
        await ingest_lock.cleanup()


async def ingest_html(
    *,
    background_tasks: BackgroundTasks | None,
    body: LocalHtmlIngestRequest,
    tenant_id: UUID,
    account_id: str,
    db: Session,
    ingestion_run_id: UUID | None = None,
    ingestion_kind: str | None = None,
) -> DBDocument:
    """
    Shared implementation for connector-style ingestion of local HTML content.

    Notes:
    - Kept queue-aware, similar to URL ingest:
      - Enqueue when task queue is enabled
      - Otherwise, when `background_tasks` is None, run inline (connector context)
    - Currently gated by URL_INGEST_ENABLED for backward-compatible security semantics.
    """
    if not settings.URL_INGEST_ENABLED:
        raise HTTPException(status_code=400, detail="URL ingestion is disabled")

    dataset = dataset_service.resolve_writable_dataset(db, tenant_id, account_id, body.dataset_id)
    ingest_file = ingestion_sources.write_local_html_ingest_file(body=body, tenant_id=tenant_id)
    source_lease = source_persistence.SourceFileLease(ingest_file.file_path)
    try:
        return await _ingest_local_html_request_with_source(
            background_tasks=background_tasks,
            body=body,
            tenant_id=tenant_id,
            account_id=account_id,
            db=db,
            ingestion_run_id=ingestion_run_id,
            ingestion_kind=ingestion_kind,
            ingest_file=ingest_file,
            dataset=dataset,
            source_lease=source_lease,
        )
    finally:
        await source_lease.cleanup_source()


async def _ingest_local_html_request_with_source(
    *,
    background_tasks: BackgroundTasks | None,
    body: LocalHtmlIngestRequest,
    tenant_id: UUID,
    account_id: str,
    db: Session,
    ingestion_run_id: UUID | None,
    ingestion_kind: str | None,
    ingest_file: ingestion_sources.LocalHtmlIngestFile,
    dataset: Dataset,
    source_lease: source_persistence.SourceFileLease,
) -> DBDocument:
    content_type = "text/html"
    source_url = str(body.source_url or "").strip()
    if not source_url:
        source_url = None
    url_normalized = normalize_url_for_dedup(source_url) if source_url else None

    prepared = _prepare_document_ingestion(
        db=db,
        tenant_id=tenant_id,
        dataset=dataset,
        filename=ingest_file.filename,
        file_ext=ingest_file.file_ext,
        requested_parser_backend=body.parser_backend,
        requested_chunk_strategy=body.chunk_strategy,
        pipeline=body.pipeline,
        source_url=source_url,
        preserve_pdf_auto=False,
    )
    ingestion_run_id = _create_local_html_ingestion_run(
        db=db,
        tenant_id=tenant_id,
        dataset=dataset,
        account_id=account_id,
        ingestion_run_id=ingestion_run_id,
        ingestion_kind=ingestion_kind,
        body=body,
        source_url=source_url,
        content_type=content_type,
        pipeline=prepared.pipeline,
    )

    doc_metadata = _build_local_html_document_metadata(
        body=body,
        source_url=source_url,
        url_normalized=url_normalized,
        fetched_at_iso=ingest_file.fetched_at_iso,
        content_type=content_type,
        pipeline=prepared.pipeline,
    )
    doc_metadata, pipeline_hash = _finalize_document_metadata(
        doc_metadata,
        content_sha256=ingest_file.content_sha256,
        pipeline_options=prepared.policy.pipeline_options,
        ingestion_meta=prepared.policy.ingestion_meta,
        ingestion_run_id=ingestion_run_id,
        ingestion_kind=ingestion_kind,
        default_kind="connector_html",
        parser_backend_resolved=str(doc_metadata.get("parser_backend_resolved") or "").strip() or None,
    )
    if settings.UPLOAD_DEDUP_ENABLED and ingest_file.content_sha256:
        duplicate = source_persistence.find_duplicate_document(
            db,
            tenant_id=tenant_id,
            dataset_id=dataset.id,
            file_sha256=ingest_file.content_sha256,
            pipeline_hash=pipeline_hash,
        )
        if duplicate is not None:
            with contextlib.suppress(OSError):
                ingest_file.file_path.unlink(missing_ok=True)
            return await _reuse_duplicate_document_for_ingest(
                background_tasks=background_tasks,
                db=db,
                tenant_id=tenant_id,
                account_id=account_id,
                duplicate=duplicate,
                content_sha256=ingest_file.content_sha256,
                pipeline_hash=pipeline_hash,
            )

    _enforce_url_upload_quota(
        db,
        tenant_id=tenant_id,
        additional_bytes=ingest_file.file_size,
        final_path=ingest_file.file_path,
    )
    stored_path = await source_persistence.store_document_source(
        file_path=ingest_file.file_path,
        tenant_id=tenant_id,
        dataset_id=dataset.id,
        document_id=ingest_file.file_id,
        extension=ingest_file.file_ext,
        content_type=content_type,
    )
    source_lease.set_stored_source(stored_path, document_metadata=doc_metadata)
    if is_object_storage_uri(stored_path):
        store = get_document_object_store()
        if store is not None:
            doc_metadata.update(document_object_store_metadata(store))

    source_lease.transfer()
    try:
        return await _persist_and_process_ingested_document(
            db=db,
            background_tasks=background_tasks,
            tenant_id=tenant_id,
            account_id=account_id,
            dataset=dataset,
            file_id=ingest_file.file_id,
            filename=ingest_file.filename,
            file_ext=ingest_file.file_ext,
            file_size=ingest_file.file_size,
            file_path=stored_path,
            processing_file_path=ingest_file.file_path,
            source_ref=(source_url or ingest_file.filename)[:1000] if (source_url or ingest_file.filename) else None,
            doc_metadata=doc_metadata,
            pipeline_hash=pipeline_hash,
            pipeline=prepared.pipeline,
            ingestion_run_id=ingestion_run_id,
        )
    except source_persistence.DuplicatePersistedDocumentError as exc:
        return await _reuse_duplicate_document_for_ingest(
            background_tasks=background_tasks,
            db=db,
            tenant_id=tenant_id,
            account_id=account_id,
            duplicate=exc.document,
            content_sha256=ingest_file.content_sha256,
            pipeline_hash=pipeline_hash,
        )

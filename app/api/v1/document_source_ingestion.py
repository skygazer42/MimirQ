"""Shared URL and connector HTML document-ingestion workflows."""

import asyncio
import contextlib
import hashlib
import shutil
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi import BackgroundTasks, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.schemas.document import DocumentPipelineOptions, LocalHtmlIngestRequest, UrlUploadRequest
from app.api.utils.document_dispatch import schedule_document_processing
from app.api.utils.pipeline_options import (
    _validate_chunk_params as _validate_chunk_params,
)
from app.api.utils.upload import (
    _sanitize_filename,
    compute_file_hash,
)
from app.api.utils.url_ingest import URLDownloadOptions, download_url_to_path, validate_url_for_ingest
from app.api.v1.document_processing import (
    retry_document_processing as retry_document_processing,
)
from app.core.config import settings
from app.core.database import SessionLocal
from app.models.dataset import Dataset
from app.models.document import Document as DBDocument
from app.parsing.factory import parser_factory
from app.rag.chunking.factory import chunker_factory
from app.rag.core.logging import get_logger
from app.rag.preprocessing.html_canonical import extract_canonical_url, normalize_url_for_dedup
from app.services import dataset_service, ingestion_run_service
from app.services.document_dedup_service import (
    DUPLICATE_DOCUMENT_PROCESSING_DETAIL,
    _find_duplicate_document,
    _find_duplicate_document_for_persist_conflict,
)
from app.services.document_dedup_service import (
    DuplicatePersistedDocumentError as _DuplicatePersistedDocumentError,
)
from app.services.document_dedup_service import (
    document_matches_dedup_identity as _document_matches_dedup_identity,
)
from app.services.document_dedup_service import (
    is_document_dedup_integrity_error as _is_document_dedup_integrity_error,
)
from app.services.document_identity import (
    build_document_dedup_key,
    compute_pipeline_hash,
    get_content_sha256,
    set_content_sha256,
    sync_pipeline_execution_identity,
)
from app.services.document_index_channel_service import reconcile_document_index_channels
from app.services.ingestion_policy import (
    match_ingestion_rule,
    parse_ingestion_policy_from_metadata,
    resolve_governance_profile_ref,
)
from app.services.pipeline_config import (
    merge_pipeline_options,
    resolve_pipeline_effective,
    upsert_pipeline_metadata,
)
from app.storage.object.runtime import (
    document_object_store_metadata,
    get_document_object_store,
    get_object_store_for_uri,
    is_object_storage_uri,
    object_store_backend_config,
    parse_object_storage_uri,
)
from app.types.pipeline import PipelineOptions

logger = get_logger("api.documents")
HTML_FILE_EXTENSION = ".html"


@dataclass
class ResolvedDocumentIngestionPolicy:
    parser_backend_choice: str
    chunk_strategy_choice: str
    pipeline_options: PipelineOptions
    ingestion_meta: dict[str, Any] | None


@dataclass
class ResolvedDocumentPipeline:
    parser_backend: str
    chunk_strategy: str


@dataclass
class UrlIngestFile:
    file_id: UUID
    final_path: Path
    file_ext: str
    downloaded: Any
    content_type: str
    fetched_at_iso: str
    content_sha256: str


@dataclass
class LocalHtmlIngestFile:
    file_id: UUID
    file_path: Path
    file_ext: str
    filename: str
    file_size: int
    fetched_at_iso: str
    content_sha256: str


@dataclass
class UrlSourceMetadata:
    final_url: str
    normalized_requested: str | None
    normalized_final: str | None
    canonical_url: str | None
    normalized_canonical: str | None
    normalized_url: str | None
    last_modified_at: str
    last_modified_source: str
    last_modified_raw: str | None
    etag: str | None


@dataclass
class PreparedDocumentIngestion:
    policy: ResolvedDocumentIngestionPolicy
    pipeline: ResolvedDocumentPipeline


async def _ingest_url_upload_request(
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
    if not bool(settings.URL_INGEST_ENABLED):
        raise HTTPException(status_code=400, detail="URL ingestion is disabled")

    url = await validate_url_for_ingest(str(body.url or ""))
    dataset = dataset_service.resolve_writable_dataset(db, tenant_id, account_id, body.dataset_id)
    ingest_file = await _download_url_ingest_file(url=url, body=body, tenant_id=tenant_id)
    source = await _url_source_metadata(url=url, ingest_file=ingest_file)
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

    if bool(settings.UPLOAD_DEDUP_ENABLED) and ingest_file.content_sha256:
        duplicate = _find_duplicate_document(
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
    stored_path = await _store_ingested_source(
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
    except _DuplicatePersistedDocumentError as exc:
        return await _reuse_duplicate_document_for_ingest(
            background_tasks=background_tasks,
            db=db,
            tenant_id=tenant_id,
            account_id=account_id,
            duplicate=exc.document,
            content_sha256=ingest_file.content_sha256,
            pipeline_hash=pipeline_hash,
        )


async def _ingest_local_html_request(
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
    if not bool(settings.URL_INGEST_ENABLED):
        raise HTTPException(status_code=400, detail="URL ingestion is disabled")

    dataset = dataset_service.resolve_writable_dataset(db, tenant_id, account_id, body.dataset_id)
    ingest_file = _write_local_html_ingest_file(body=body, tenant_id=tenant_id)
    content_type = "text/html"
    source_url = str(body.source_url or "").strip() or None
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
    if bool(settings.UPLOAD_DEDUP_ENABLED) and ingest_file.content_sha256:
        duplicate = _find_duplicate_document(
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
    stored_path = await _store_ingested_source(
        file_path=ingest_file.file_path,
        tenant_id=tenant_id,
        dataset_id=dataset.id,
        document_id=ingest_file.file_id,
        extension=ingest_file.file_ext,
        content_type=content_type,
    )
    if is_object_storage_uri(stored_path):
        store = get_document_object_store()
        if store is not None:
            doc_metadata.update(document_object_store_metadata(store))

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
    except _DuplicatePersistedDocumentError as exc:
        return await _reuse_duplicate_document_for_ingest(
            background_tasks=background_tasks,
            db=db,
            tenant_id=tenant_id,
            account_id=account_id,
            duplicate=exc.document,
            content_sha256=ingest_file.content_sha256,
            pipeline_hash=pipeline_hash,
        )


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
    pipeline: ResolvedDocumentPipeline,
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
    if bool(settings.UPLOAD_DEDUP_ENABLED):
        db_document.dedup_key = build_document_dedup_key(
            content_sha256=get_content_sha256(doc_metadata),
            pipeline_hash=pipeline_hash,
        )
    keep_local_processing_file = False
    try:
        db.add(db_document)
    except Exception:
        with contextlib.suppress(Exception):
            db.rollback()
        await _cleanup_unpersisted_ingested_source(
            str(file_path),
            document_metadata=dict(getattr(db_document, "doc_metadata", None) or {}),
        )
        _unlink_ingest_temp(processing_file_path)
        raise

    try:
        db.commit()
    except IntegrityError as exc:
        with contextlib.suppress(Exception):
            db.rollback()
        duplicate = (
            _find_duplicate_document_for_persist_conflict(db, db_document=db_document)
            if _is_document_dedup_integrity_error(exc)
            else None
        )
        await _cleanup_unpersisted_ingested_source(
            str(file_path),
            document_metadata=dict(getattr(db_document, "doc_metadata", None) or {}),
        )
        _unlink_ingest_temp(processing_file_path)
        if duplicate is not None:
            raise _DuplicatePersistedDocumentError(duplicate) from exc
        raise
    except Exception:
        with contextlib.suppress(Exception):
            db.rollback()
        await _cleanup_commit_ambiguous_ingested_source(
            document_id=file_id,
            stored_path=str(file_path),
            file_path=processing_file_path,
            document_metadata=dict(getattr(db_document, "doc_metadata", None) or {}),
        )
        raise

    try:
        db.refresh(db_document)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Document committed but refresh failed: %s", str(exc)[:200])

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
        keep_local_processing_file = await schedule_document_processing(
            db=db,
            background_tasks=background_tasks,
            tenant_id=tenant_id,
            document_id=file_id,
            file_path=processing_file_path,
            requested_by=account_id,
            pipeline_hash=pipeline_hash,
            parser_backend=pipeline.parser_backend,
            chunk_strategy=pipeline.chunk_strategy,
            db_document=db_document,
        )
    finally:
        if is_object_storage_uri(str(file_path)) and not keep_local_processing_file:
            _unlink_ingest_temp(processing_file_path)
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
    status0 = str(getattr(duplicate, "status", "") or "").strip().lower()
    if status0 in {"pending", "processing"}:
        if _document_matches_dedup_identity(
            duplicate,
            content_sha256=content_sha256,
            pipeline_hash=pipeline_hash,
        ):
            return duplicate
        raise HTTPException(status_code=409, detail=DUPLICATE_DOCUMENT_PROCESSING_DETAIL)

    meta = dict(getattr(duplicate, "doc_metadata", None) or {})
    sync_pipeline_execution_identity(
        meta,
        content_sha256=content_sha256,
        pipeline_hash=pipeline_hash,
        parser_backend_resolved=str(meta.get("parser_backend_resolved") or "").strip() or None,
    )
    duplicate.doc_metadata = meta
    if hasattr(duplicate, "dedup_key"):
        duplicate.dedup_key = build_document_dedup_key(content_sha256=content_sha256, pipeline_hash=pipeline_hash)
    db.commit()
    db.refresh(duplicate)

    if status0 == "failed":
        if background_tasks is None:
            raise HTTPException(status_code=409, detail="Failed duplicate requires retry scheduling context")
        await retry_document_processing(
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


def _compute_pipeline_hash(doc_metadata: dict) -> str:
    return compute_pipeline_hash(doc_metadata)


def _parse_datetime_best_effort(raw: str | None) -> datetime | None:
    """
    Best-effort datetime parser for connector source metadata.

    Supports:
    - HTTP-date (e.g. Last-Modified: "Wed, 21 Oct 2015 07:28:00 GMT")
    - ISO 8601 timestamps (e.g. "2026-03-04T10:00:00Z")
    """
    value = str(raw or "").strip()
    if not value:
        return None

    with contextlib.suppress(Exception):
        dt = parsedate_to_datetime(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    with contextlib.suppress(Exception):
        iso = value
        if iso.endswith("Z"):
            iso = iso[:-1] + "+00:00"
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    return None


def _normalize_datetime_utc_iso(raw: str | None) -> str | None:
    dt = _parse_datetime_best_effort(raw)
    if dt is None:
        return None
    return dt.isoformat()


def _ext_from_filename(name: str | None) -> str | None:
    if not name:
        return None
    ext = Path(str(name)).suffix.lower()
    return ext if ext else None


def _ext_from_content_type(content_type: str) -> str | None:
    if not content_type:
        return None
    if content_type in {"text/html"}:
        return HTML_FILE_EXTENSION
    if content_type in {"text/plain"}:
        return ".txt"
    if content_type in {"text/markdown", "text/x-markdown"}:
        return ".md"
    if content_type in {"application/pdf"}:
        return ".pdf"
    if content_type in {"application/json"}:
        return ".json"
    if content_type in {"text/xml", "application/xml", "application/rss+xml", "application/atom+xml"}:
        return ".xml"
    return None


def _assert_allowed_file_ext(file_ext: str) -> str:
    file_ext = file_ext.lower()
    if file_ext not in settings.allowed_extensions_list:
        raise HTTPException(
            status_code=400, detail=f"Unsupported file type. Allowed: {settings.allowed_extensions_list}"
        )
    return file_ext


def _resolve_url_file_ext(*, filename: str | None, url: str, content_type: str) -> str:
    file_ext = _ext_from_filename(filename)
    if not file_ext:
        from urllib.parse import urlparse

        parsed = urlparse(url)
        file_ext = _ext_from_filename(Path(parsed.path).name)
    if not file_ext:
        file_ext = _ext_from_content_type(content_type)
    if not file_ext:
        if content_type.startswith("text/"):
            file_ext = ".txt"
        else:
            raise HTTPException(status_code=400, detail=f"Unsupported content-type: {content_type or 'unknown'}")
    return _assert_allowed_file_ext(file_ext)


def _resolve_local_html_file_ext(safe_name: str) -> str:
    file_ext = Path(safe_name).suffix.lower() or HTML_FILE_EXTENSION
    if file_ext == ".htm":
        file_ext = HTML_FILE_EXTENSION
    if not file_ext.startswith("."):
        file_ext = "." + file_ext
    return _assert_allowed_file_ext(file_ext)


def _finalize_url_download(temp_path: Path, final_path: Path) -> None:
    try:
        temp_path.replace(final_path)
    except Exception:
        try:
            shutil.move(str(temp_path), str(final_path))
        except Exception as exc:  # noqa: BLE001
            with contextlib.suppress(OSError):
                temp_path.unlink(missing_ok=True)
            raise HTTPException(
                status_code=500, detail=f"failed to finalize downloaded file: {str(exc)[:120]}"
            ) from exc


def _read_html_prefix(path: Path) -> str:
    with path.open("rb") as f:
        return f.read(200_000).decode("utf-8", "ignore")


async def _extract_url_canonical_metadata(
    *,
    content_type: str,
    final_path: Path,
    url_final: str,
) -> tuple[str | None, str | None]:
    if not content_type or "html" not in content_type:
        return None, None

    try:
        html_prefix = await asyncio.to_thread(_read_html_prefix, final_path)
        url_canonical = extract_canonical_url(html_prefix, base_url=url_final)
        url_normalized_canonical = normalize_url_for_dedup(url_canonical) if url_canonical else None
        return url_canonical, url_normalized_canonical
    except Exception:
        return None, None


def _document_pipeline_options(pipeline: DocumentPipelineOptions | None) -> PipelineOptions:
    return PipelineOptions(**(pipeline.model_dump(exclude_none=True) if pipeline else {}))


def _normalized_dataset_default(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip().lower()
    return None


def _dataset_pipeline_defaults(dataset: Dataset | None) -> tuple[str, str]:
    dataset_default_pb = None
    dataset_default_cs = None
    if dataset is not None:
        ds_meta = getattr(dataset, "dataset_metadata", None)
        if isinstance(ds_meta, dict):
            dataset_default_pb = _normalized_dataset_default(ds_meta.get("default_parser_backend"))
            dataset_default_cs = _normalized_dataset_default(ds_meta.get("default_chunk_strategy"))

    default_pb_eff = dataset_default_pb or str(settings.DEFAULT_PARSER_BACKEND or "auto").strip().lower() or "auto"
    default_cs_eff = (
        dataset_default_cs
        or str(settings.DEFAULT_CHUNK_STRATEGY or "langchain_recursive").strip().lower()
        or "langchain_recursive"
    )
    return default_pb_eff, default_cs_eff


def _rule_backend_choices(
    *,
    matched_rule: Any,
    parser_backend_choice: str,
    chunk_strategy_choice: str,
    default_pb_eff: str,
    default_cs_eff: str,
) -> tuple[str, str]:
    req_pb = (parser_backend_choice or "").strip().lower()
    if req_pb in {"", "auto", default_pb_eff} and matched_rule.parser_backend:
        parser_backend_choice = str(matched_rule.parser_backend)

    req_cs = (chunk_strategy_choice or "").strip().lower()
    if req_cs in {"", default_cs_eff} and matched_rule.chunk_strategy:
        chunk_strategy_choice = str(matched_rule.chunk_strategy)

    return parser_backend_choice, chunk_strategy_choice


def _rule_preprocess_steps(matched_rule: Any) -> list[dict[str, Any]]:
    pp = getattr(matched_rule, "preprocess", None)
    steps = getattr(pp, "steps", None) if pp is not None and bool(getattr(pp, "enabled", True)) else None
    if not isinstance(steps, list) or not steps:
        return []
    return [
        {
            "id": str(getattr(s, "id", "") or "").strip(),
            "params": dict(getattr(s, "params", {}) or {}),
        }
        for s in steps
    ]


def _rule_pipeline_patch(db: Session, *, tenant_id: UUID, matched_rule: Any) -> tuple[PipelineOptions, str | None]:
    patch_dict: dict[str, Any] = {}
    profile_ref = getattr(matched_rule, "governance_profile_ref", None)
    normalized_profile_ref = profile_ref.strip() if isinstance(profile_ref, str) and profile_ref.strip() else None
    if normalized_profile_ref:
        try:
            resolved = resolve_governance_profile_ref(db=db, tenant_id=tenant_id, profile_ref=normalized_profile_ref)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"Invalid governance_profile_ref: {str(exc)[:120]}") from exc
        patch_dict.update(dict(resolved.pipeline_patch or {}))
        if resolved.regex_rules:
            patch_dict["governance_regex_rules"] = list(resolved.regex_rules)

    patch_dict.update(dict(getattr(matched_rule, "pipeline_patch", None) or {}))
    policy_patch = PipelineOptions(**patch_dict) if patch_dict else PipelineOptions()
    return policy_patch, normalized_profile_ref


def _policy_from_dataset(dataset: Dataset | None):
    dataset_meta = (getattr(dataset, "dataset_metadata", None) or {}) if dataset is not None else {}
    return parse_ingestion_policy_from_metadata(dataset_meta if isinstance(dataset_meta, dict) else {})  # type: ignore[arg-type]


def _resolve_document_ingestion_policy(
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
) -> ResolvedDocumentIngestionPolicy:
    pipeline_options = _document_pipeline_options(pipeline)
    policy = _policy_from_dataset(dataset)
    matched_rule = match_ingestion_rule(policy, filename=filename, file_ext=file_ext)
    default_pb_eff, default_cs_eff = _dataset_pipeline_defaults(dataset)

    parser_backend_choice = str(requested_parser_backend or default_pb_eff)
    chunk_strategy_choice = str(requested_chunk_strategy or default_cs_eff)
    policy_patch = PipelineOptions()
    ingestion_meta: dict[str, Any] | None = None

    if matched_rule is not None:
        parser_backend_choice, chunk_strategy_choice = _rule_backend_choices(
            matched_rule=matched_rule,
            parser_backend_choice=parser_backend_choice,
            chunk_strategy_choice=chunk_strategy_choice,
            default_pb_eff=default_pb_eff,
            default_cs_eff=default_cs_eff,
        )
        preprocess_steps = _rule_preprocess_steps(matched_rule)
        policy_patch, profile_ref = _rule_pipeline_patch(db, tenant_id=tenant_id, matched_rule=matched_rule)
        ingestion_meta = {
            "version": str(getattr(policy, "version", "1") if policy is not None else "1"),
            "rule": {"id": matched_rule.id, "name": matched_rule.name},
            "preprocess": {"enabled": bool(preprocess_steps), "steps": preprocess_steps},
            "governance_profile_ref": profile_ref,
            "source_url": source_url,
        }

    return ResolvedDocumentIngestionPolicy(
        parser_backend_choice=parser_backend_choice,
        chunk_strategy_choice=chunk_strategy_choice,
        pipeline_options=merge_pipeline_options(policy_patch, pipeline_options),
        ingestion_meta=ingestion_meta,
    )


def _resolve_document_pipeline(
    *,
    file_ext: str,
    parser_backend_choice: str,
    chunk_strategy_choice: str,
    preserve_pdf_auto: bool,
) -> ResolvedDocumentPipeline:
    try:
        requested_parser_backend = (parser_backend_choice or "").strip().lower()
        if preserve_pdf_auto and file_ext == ".pdf" and requested_parser_backend in {"", "auto"}:
            resolved_parser_backend = "auto"
        else:
            resolved_parser_backend = parser_factory.resolve_backend(file_ext, parser_backend_choice)
        resolved_chunk_strategy = chunker_factory.resolve_strategy(chunk_strategy_choice)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return ResolvedDocumentPipeline(parser_backend=resolved_parser_backend, chunk_strategy=resolved_chunk_strategy)


def _validate_pipeline_effective_for_strategy(
    *,
    dataset: Dataset,
    pipeline_options: PipelineOptions,
    resolved_chunk_strategy: str,
) -> None:
    pipeline_effective = resolve_pipeline_effective(
        dataset_metadata=(getattr(dataset, "dataset_metadata", None) or {}),
        document_metadata={},
        request_overrides=pipeline_options,
    )
    if resolved_chunk_strategy not in chunker_factory.INTEGRATED_PIPELINE_STRATEGIES:
        _validate_chunk_params(pipeline_effective.chunk_size, pipeline_effective.chunk_overlap)


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
            dataset_id=getattr(dataset, "id", None),
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

    pipeline_hash = _compute_pipeline_hash(doc_metadata)
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


def _unlink_ingest_temp(path: Path) -> None:
    with contextlib.suppress(OSError):
        path.unlink(missing_ok=True)


async def _store_ingested_source(
    *,
    file_path: Path,
    tenant_id: UUID,
    dataset_id: UUID,
    document_id: UUID,
    extension: str,
    content_type: str | None,
) -> str:
    store = get_document_object_store()
    if store is None:
        return str(file_path)
    try:
        return await asyncio.to_thread(
            store.upload_document_file,
            file_path=file_path,
            tenant_id=str(tenant_id),
            dataset_id=str(dataset_id),
            document_id=str(document_id),
            extension=extension,
            content_type=content_type,
        )
    except Exception:
        _unlink_ingest_temp(file_path)
        raise


async def _cleanup_unpersisted_ingested_source(
    stored_path: str,
    *,
    document_metadata: dict[str, Any] | None = None,
) -> None:
    if not is_object_storage_uri(stored_path):
        return
    try:
        ref = parse_object_storage_uri(stored_path)
        store = get_object_store_for_uri(stored_path, document_metadata=document_metadata)
        backend = object_store_backend_config(store)
        if ref.bucket != str(backend.get("bucket", "") or "").strip():
            return
        await asyncio.to_thread(store.delete_object, object_name=ref.object_name)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to delete unpersisted ingest object: %s", str(exc)[:200])


def _fresh_session_document_exists(*, document_id: UUID) -> bool | None:
    try:
        check_db = SessionLocal()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to open verification session after commit error: %s", str(exc)[:200])
        return None

    try:
        getter = getattr(check_db, "get", None)
        if callable(getter):
            return getter(DBDocument, document_id) is not None
        query = getattr(check_db, "query", None)
        if callable(query):
            row = query(DBDocument).filter(DBDocument.id == document_id).first()
            return row is not None
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to verify document existence after commit error: %s", str(exc)[:200])
        return None
    finally:
        with contextlib.suppress(Exception):
            check_db.close()

    return None


async def _cleanup_commit_ambiguous_ingested_source(
    *,
    document_id: UUID,
    stored_path: str,
    file_path: Path,
    document_metadata: dict[str, Any] | None = None,
) -> None:
    document_exists = _fresh_session_document_exists(document_id=document_id)
    object_backed = is_object_storage_uri(stored_path)
    if document_exists is False:
        await _cleanup_unpersisted_ingested_source(stored_path, document_metadata=document_metadata)
        _unlink_ingest_temp(file_path)
        return
    if object_backed:
        _unlink_ingest_temp(file_path)


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
            initial_status=str(getattr(db_document, "status", "") or "pending"),
            doc_meta=dict(doc_metadata),
        )


async def _download_url_ingest_file(*, url: str, body: UrlUploadRequest, tenant_id: UUID) -> UrlIngestFile:
    upload_dir = Path(settings.UPLOAD_DIR) / str(tenant_id)
    upload_dir.mkdir(parents=True, exist_ok=True)
    file_id = uuid.uuid4()
    temp_path = upload_dir / f"{file_id}.urltmp"
    downloaded = await download_url_to_path(
        url,
        temp_path,
        options=URLDownloadOptions(
            max_bytes=int(settings.URL_INGEST_MAX_BYTES or settings.MAX_FILE_SIZE),
            timeout_sec=float(settings.URL_INGEST_TIMEOUT_SEC or 30.0),
            follow_redirects=bool(settings.URL_INGEST_FOLLOW_REDIRECTS),
            user_agent=(body.user_agent or None),
            extra_headers=(body.fetch_headers or None),
        ),
    )

    content_type = (downloaded.content_type or "").split(";", 1)[0].strip().lower()
    file_ext = _resolve_url_file_ext(filename=body.filename, url=url, content_type=content_type)
    final_path = upload_dir / f"{file_id}{file_ext}"
    _finalize_url_download(temp_path, final_path)
    content_sha256 = await asyncio.to_thread(compute_file_hash, final_path)
    return UrlIngestFile(
        file_id=file_id,
        final_path=final_path,
        file_ext=file_ext,
        downloaded=downloaded,
        content_type=content_type,
        fetched_at_iso=datetime.now(timezone.utc).isoformat(),
        content_sha256=content_sha256,
    )


def _write_local_html_ingest_file(*, body: LocalHtmlIngestRequest, tenant_id: UUID) -> LocalHtmlIngestFile:
    upload_dir = Path(settings.UPLOAD_DIR) / str(tenant_id)
    upload_dir.mkdir(parents=True, exist_ok=True)

    data = str(body.html or "").encode("utf-8", "ignore")
    if int(settings.MAX_FILE_SIZE or 0) > 0 and len(data) > int(settings.MAX_FILE_SIZE):
        raise HTTPException(status_code=400, detail="File too large")

    safe_name = _sanitize_filename(body.filename or "confluence-page.html")
    file_ext = _resolve_local_html_file_ext(safe_name)
    file_id = uuid.uuid4()
    file_path = upload_dir / f"{file_id}{file_ext}"
    try:
        file_path.write_bytes(data)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"failed to write html file: {str(exc)[:120]}") from exc

    return LocalHtmlIngestFile(
        file_id=file_id,
        file_path=file_path,
        file_ext=file_ext,
        filename=safe_name,
        file_size=int(len(data)),
        fetched_at_iso=datetime.now(timezone.utc).isoformat(),
        content_sha256=hashlib.sha256(data).hexdigest(),
    )


async def _url_source_metadata(*, url: str, ingest_file: UrlIngestFile) -> UrlSourceMetadata:
    downloaded = ingest_file.downloaded
    last_modified_raw = str(getattr(downloaded, "last_modified", "") or "").strip() or None
    last_modified_norm = _normalize_datetime_utc_iso(last_modified_raw) if last_modified_raw else None
    etag_raw = str(getattr(downloaded, "etag", "") or "").strip() or None
    if etag_raw and len(etag_raw) > 500:
        etag_raw = etag_raw[:500]

    url_final = str(getattr(downloaded, "final_url", "") or url).strip() or url
    url_normalized_requested = normalize_url_for_dedup(url)
    url_normalized_final = normalize_url_for_dedup(url_final)
    url_canonical, url_normalized_canonical = await _extract_url_canonical_metadata(
        content_type=ingest_file.content_type,
        final_path=ingest_file.final_path,
        url_final=url_final,
    )
    url_normalized = url_normalized_canonical or url_normalized_final or url_normalized_requested
    return UrlSourceMetadata(
        final_url=url_final,
        normalized_requested=url_normalized_requested,
        normalized_final=url_normalized_final,
        canonical_url=url_canonical,
        normalized_canonical=url_normalized_canonical,
        normalized_url=url_normalized,
        last_modified_at=last_modified_norm or ingest_file.fetched_at_iso,
        last_modified_source="http:last-modified" if last_modified_norm else "fallback:fetched_at",
        last_modified_raw=last_modified_raw,
        etag=etag_raw,
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
) -> PreparedDocumentIngestion:
    ingestion_policy = _resolve_document_ingestion_policy(
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
    resolved_pipeline = _resolve_document_pipeline(
        file_ext=file_ext,
        parser_backend_choice=ingestion_policy.parser_backend_choice,
        chunk_strategy_choice=ingestion_policy.chunk_strategy_choice,
        preserve_pdf_auto=preserve_pdf_auto,
    )
    _validate_pipeline_effective_for_strategy(
        dataset=dataset,
        pipeline_options=ingestion_policy.pipeline_options,
        resolved_chunk_strategy=resolved_pipeline.chunk_strategy,
    )
    return PreparedDocumentIngestion(policy=ingestion_policy, pipeline=resolved_pipeline)


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
    source: UrlSourceMetadata,
    pipeline: ResolvedDocumentPipeline,
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
    pipeline: ResolvedDocumentPipeline,
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
    ingest_file: UrlIngestFile,
    source: UrlSourceMetadata,
    pipeline: ResolvedDocumentPipeline,
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
    pipeline: ResolvedDocumentPipeline,
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

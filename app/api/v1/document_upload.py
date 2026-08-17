import asyncio
import contextlib
import json
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.api.schemas.document import DocumentBatchUploadResponse, DocumentDetail
from app.api.v1.documents import UrlUploadRequest
from app.core.config import settings
from app.core.database import get_db
from app.rag.core.logging import get_logger
from app.services.document_identity import (
    build_document_dedup_key,
    get_content_sha256,
    sync_pipeline_execution_identity,
)
from app.services.document_index_channel_service import reconcile_document_index_channels
from app.storage.object.minio import minio_service as minio_service
from app.storage.object.runtime import (
    document_object_storage_enabled,
    document_object_store_metadata,
    get_document_object_store,
    get_object_store_for_uri,
    is_object_storage_uri,
    object_store_backend_config,
    parse_object_storage_uri,
)
from app.tasks.locks import task_job_lock_ttl_sec

_DEFAULT_HTTP_EXCEPTION_RESPONSES = {
    400: {"description": "Bad Request"},
    403: {"description": "Forbidden"},
    404: {"description": "Not Found"},
    409: {"description": "Conflict"},
    416: {"description": "Range Not Satisfiable"},
    503: {"description": "Service Unavailable"},
}

router = APIRouter(responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
logger = get_logger(__name__)
INGEST_LOCK_UNAVAILABLE_DETAIL = "Ingest lock unavailable"
DOCUMENT_DEDUP_CONSTRAINT_NAME = "uq_documents_tenant_dataset_dedup_key_active"


class _DuplicatePersistedDocumentError(RuntimeError):
    def __init__(self, document: Any) -> None:
        super().__init__("duplicate persisted document")
        self.document = document


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


def _document_result_snapshot(document: Any, *, source_path: str | None) -> dict[str, Any]:
    return {
        "document_id": str(getattr(document, "id", "") or ""),
        "filename": str(getattr(document, "filename", "") or ""),
        "source_path": source_path,
        "status": str(getattr(document, "status", "") or ""),
        "doc_metadata": dict(getattr(document, "doc_metadata", None) or {}),
    }


def _document_object_storage_enabled() -> bool:
    return document_object_storage_enabled()


def _document_upload_path(tenant_id: UUID, document_id: UUID, extension: str) -> Path:
    upload_dir = Path(settings.UPLOAD_DIR) / str(tenant_id)
    if _document_object_storage_enabled():
        upload_dir /= ".tmp"
    upload_dir.mkdir(parents=True, exist_ok=True)
    return upload_dir / f"{document_id}{extension}"


def _unlink_upload(path: Path) -> None:
    with contextlib.suppress(OSError):
        path.unlink(missing_ok=True)


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


async def _cancel_gather_tasks(in_flight: dict[asyncio.Task[Any], int]) -> None:
    for task in in_flight:
        task.cancel()
    if in_flight:
        await asyncio.gather(*in_flight, return_exceptions=True)


async def _store_document_source(
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
        _unlink_upload(file_path)
        raise


async def _cleanup_unpersisted_source(stored_path: str, *, document_metadata: dict[str, Any] | None = None) -> None:
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
        logger.warning("Failed to delete unpersisted document object: %s", str(exc)[:200])


def _fresh_session_document_exists(*, session_factory: Any, document_id: UUID) -> bool | None:
    from app.api.v1 import documents as documents_module

    try:
        check_db = session_factory()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to open verification session after commit error: %s", str(exc)[:200])
        return None

    try:
        getter = getattr(check_db, "get", None)
        if callable(getter):
            return getter(documents_module.DBDocument, document_id) is not None
        query = getattr(check_db, "query", None)
        if callable(query):
            row = query(documents_module.DBDocument).filter(documents_module.DBDocument.id == document_id).first()
            return row is not None
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to verify document existence after commit error: %s", str(exc)[:200])
        return None
    finally:
        with contextlib.suppress(Exception):
            check_db.close()

    return None


async def _cleanup_commit_ambiguous_source(
    *,
    session_factory: Any,
    document_id: UUID,
    stored_path: str,
    file_path: Path,
    document_metadata: dict[str, Any] | None = None,
) -> None:
    document_exists = _fresh_session_document_exists(session_factory=session_factory, document_id=document_id)
    object_backed = is_object_storage_uri(stored_path)
    if document_exists is False:
        await _cleanup_unpersisted_source(stored_path, document_metadata=document_metadata)
        _unlink_upload(file_path)
        return
    if object_backed:
        _unlink_upload(file_path)


def _find_duplicate_document_for_persist_conflict(db: Session, *, db_document: Any) -> Any | None:
    from app.api.v1 import documents as documents_module

    dataset_id = getattr(db_document, "dataset_id", None)
    tenant_id = getattr(db_document, "tenant_id", None)
    if not isinstance(dataset_id, UUID) or not isinstance(tenant_id, UUID):
        return None
    doc_metadata = dict(getattr(db_document, "doc_metadata", None) or {})
    file_sha256 = get_content_sha256(doc_metadata)
    pipeline_hash = str(doc_metadata.get("pipeline_hash") or "").strip()
    if file_sha256 and pipeline_hash:
        return documents_module._find_duplicate_document(
            db,
            tenant_id=tenant_id,
            dataset_id=dataset_id,
            file_sha256=file_sha256,
            pipeline_hash=pipeline_hash,
        )
    return None


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
    if not bool(getattr(settings, "UPLOAD_DEDUP_ENABLED", False)):
        return
    if not bool(getattr(settings, "TASK_QUEUE_ENABLED", False)):
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


def _retain_ingest_lock_if_task_handed_off(document: Any, *, ingest_lock: _IngestLockLease) -> None:
    if str((getattr(document, "doc_metadata", None) or {}).get("task_id") or "").strip():
        ingest_lock.retain()


def _build_document_dedup_key(*, file_sha256: str | None, pipeline_hash: str | None) -> str | None:
    return build_document_dedup_key(content_sha256=file_sha256, pipeline_hash=pipeline_hash)


def _document_matches_dedup_identity(
    document: Any,
    *,
    file_sha256: str,
    pipeline_hash: str,
) -> bool:
    expected = _build_document_dedup_key(file_sha256=file_sha256, pipeline_hash=pipeline_hash)
    if expected and str(getattr(document, "dedup_key", "") or "").strip() == expected:
        return True
    metadata = dict(getattr(document, "doc_metadata", None) or {})
    return bool(
        expected
        and get_content_sha256(metadata) == str(file_sha256 or "").strip().lower()
        and str(metadata.get("pipeline_hash") or "").strip() == str(pipeline_hash or "").strip()
    )


def _is_document_dedup_integrity_error(exc: IntegrityError) -> bool:
    diag = getattr(getattr(exc, "orig", None), "diag", None)
    if str(getattr(diag, "constraint_name", "") or "").strip() == DOCUMENT_DEDUP_CONSTRAINT_NAME:
        return True
    message = str(getattr(exc, "orig", "") or exc)
    return DOCUMENT_DEDUP_CONSTRAINT_NAME in message


def _sync_duplicate_document_pipeline_identity(
    duplicate_document: Any,
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
    doc_metadata["pipeline_hash"] = str(pipeline_hash or "").strip() or None
    if hasattr(duplicate_document, "dedup_key"):
        duplicate_document.dedup_key = _build_document_dedup_key(file_sha256=file_sha256, pipeline_hash=pipeline_hash)


async def _retry_failed_persisted_duplicate(
    document: Any,
    *,
    background_tasks: BackgroundTasks,
    tenant_id: UUID,
    account_id: str,
    db: Session,
) -> None:
    if str(getattr(document, "status", "") or "").lower() != "failed":
        return
    from app.api.v1 import documents as documents_module

    await documents_module.retry_document_processing(
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


async def _persist_uploaded_document(db: Session, db_document: Any, *, file_path: Path) -> None:
    try:
        db.add(db_document)
    except Exception:
        with contextlib.suppress(Exception):
            db.rollback()
        await _cleanup_unpersisted_source(
            str(getattr(db_document, "file_path", "") or ""),
            document_metadata=dict(getattr(db_document, "doc_metadata", None) or {}),
        )
        _unlink_upload(file_path)
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
        await _cleanup_unpersisted_source(
            str(getattr(db_document, "file_path", "") or ""),
            document_metadata=dict(getattr(db_document, "doc_metadata", None) or {}),
        )
        _unlink_upload(file_path)
        if duplicate is not None:
            raise _DuplicatePersistedDocumentError(duplicate) from exc
        raise
    except Exception:
        # The server may have committed even when the client lost the acknowledgement.
        from app.api.v1 import documents as documents_module

        with contextlib.suppress(Exception):
            db.rollback()
        document_id = getattr(db_document, "id", None)
        if isinstance(document_id, UUID):
            await _cleanup_commit_ambiguous_source(
                session_factory=documents_module.SessionLocal,
                document_id=document_id,
                stored_path=str(getattr(db_document, "file_path", "") or ""),
                file_path=file_path,
                document_metadata=dict(getattr(db_document, "doc_metadata", None) or {}),
            )
        else:
            _unlink_upload(file_path)
        raise

    try:
        db.refresh(db_document)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Document committed but refresh failed: %s", str(exc)[:200])


async def _run_document_processing_with_cleanup(
    file_path: Path,
    document_id: UUID,
    tenant_id: UUID,
    parser_backend: str,
    chunk_strategy: str,
) -> None:
    from app.api.v1 import documents as documents_module

    try:
        await documents_module.run_document_processing_limited(
            file_path,
            document_id,
            tenant_id,
            parser_backend,
            chunk_strategy,
        )
    finally:
        _unlink_upload(file_path)


async def _schedule_document_processing(
    *,
    background_tasks: BackgroundTasks,
    file_path: Path,
    document_id: UUID,
    tenant_id: UUID,
    account_id: str,
    pipeline_hash: str,
    parser_backend: str,
    chunk_strategy: str,
    db: Session,
    db_document: Any,
) -> bool:
    from app.api.v1 import documents as documents_module

    object_backed = is_object_storage_uri(str(getattr(db_document, "file_path", "") or ""))
    job_id = f"doc:{tenant_id}:{document_id}:{pipeline_hash}"
    queue_required = documents_module._task_queue_required()
    task_id = None
    try:
        task_id = await documents_module.enqueue_document_processing(
            tenant_id=tenant_id,
            document_id=document_id,
            requested_by=account_id,
            job_id=job_id,
        )
    except Exception as exc:  # noqa: BLE001
        if queue_required:
            logger.error("Document queue unavailable while handoff is required: %s", str(exc)[:200])
            documents_module._raise_document_processing_queue_unavailable(db=db, db_document=db_document, exc=exc)
        logger.warning("Document queue unavailable; using API background task: %s", str(exc)[:200])

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
        documents_module._raise_document_processing_queue_unavailable(db=db, db_document=db_document)

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
                documents_module.run_document_processing_limited,
                file_path,
                document_id,
                tenant_id,
                parser_backend,
                chunk_strategy,
            )
    except Exception as exc:
        documents_module._mark_document_processing_schedule_failed(db=db, db_document=db_document)
        logger.error("Failed to register document background task: %s", str(exc)[:200])
        raise
    return True


@dataclass(frozen=True)
class _UploadIdentity:
    filename: str
    file_ext: str
    upload_key: str
    source_path: str | None


@dataclass(frozen=True)
class _UploadDefaultSelection:
    parser_backend_base: str
    chunk_strategy_base: str
    default_parser_backend: str
    default_chunk_strategy: str


@dataclass(frozen=True)
class _ResolvedUploadPipeline:
    pipeline_options: Any
    ingestion_meta: dict[str, Any] | None
    resolved_parser_backend: str
    resolved_chunk_strategy: str


@dataclass(frozen=True)
class _PreparedDocumentMetadata:
    doc_metadata: dict[str, Any]
    pipeline_hash: str


def _normalize_upload_identity(file: UploadFile) -> _UploadIdentity:
    from app.api.v1 import documents as documents_module

    raw_filename = file.filename
    upload_key = documents_module._normalize_upload_key(raw_filename)
    source_path = upload_key if "/" in upload_key else None
    file.filename = documents_module._sanitize_filename(raw_filename)
    return _UploadIdentity(
        filename=str(file.filename or ""),
        file_ext=Path(str(file.filename or "")).suffix.lower(),
        upload_key=upload_key,
        source_path=source_path,
    )


def _upload_extension_allowed(file_ext: str) -> bool:
    return file_ext in settings.allowed_extensions_list


def _require_upload_extension(file_ext: str) -> None:
    if not _upload_extension_allowed(file_ext):
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type. Allowed: {settings.allowed_extensions_list}",
        )


def _dataset_upload_defaults(dataset_meta: Any) -> tuple[str | None, str | None]:
    if not isinstance(dataset_meta, dict):
        return None, None
    raw_pb = dataset_meta.get("default_parser_backend")
    raw_cs = dataset_meta.get("default_chunk_strategy")
    dataset_default_pb = raw_pb.strip().lower() if isinstance(raw_pb, str) and raw_pb.strip() else None
    dataset_default_cs = raw_cs.strip().lower() if isinstance(raw_cs, str) and raw_cs.strip() else None
    return dataset_default_pb, dataset_default_cs


def _select_upload_defaults(
    *,
    parser_backend: str,
    chunk_strategy: str,
    dataset_default_pb: str | None,
    dataset_default_cs: str | None,
) -> _UploadDefaultSelection:
    global_default_pb = str(getattr(settings, "DEFAULT_PARSER_BACKEND", "auto") or "auto").strip().lower() or "auto"
    global_default_cs = (
        str(getattr(settings, "DEFAULT_CHUNK_STRATEGY", "langchain_recursive") or "langchain_recursive").strip().lower()
        or "langchain_recursive"
    )
    parser_backend_base = parser_backend
    chunk_strategy_base = chunk_strategy
    requested_pb = (parser_backend or "").strip().lower()
    requested_cs = (chunk_strategy or "").strip().lower()
    if dataset_default_pb and requested_pb in {"", "auto", global_default_pb}:
        parser_backend_base = dataset_default_pb
    if dataset_default_cs and requested_cs in {"", global_default_cs}:
        chunk_strategy_base = dataset_default_cs
    return _UploadDefaultSelection(
        parser_backend_base=parser_backend_base,
        chunk_strategy_base=chunk_strategy_base,
        default_parser_backend=dataset_default_pb or global_default_pb,
        default_chunk_strategy=dataset_default_cs or global_default_cs,
    )


def _serialize_preprocess_steps(matched_rule: Any) -> list[dict[str, Any]]:
    preprocess = getattr(matched_rule, "preprocess", None)
    steps = (
        getattr(preprocess, "steps", None)
        if preprocess is not None and bool(getattr(preprocess, "enabled", True))
        else None
    )
    if not isinstance(steps, list) or not steps:
        return []
    return [
        {
            "id": str(getattr(step, "id", "") or "").strip(),
            "params": dict(getattr(step, "params", {}) or {}),
        }
        for step in steps
    ]


def _resolve_governance_policy_patch(
    *,
    db: Session,
    tenant_id: UUID,
    matched_rule: Any,
    governance_profile_cache: dict[str, Any] | None,
) -> tuple[dict[str, Any], str | None]:
    from app.api.v1 import documents as documents_module

    patch_dict = dict(getattr(matched_rule, "pipeline_patch", None) or {})
    profile_ref = getattr(matched_rule, "governance_profile_ref", None)
    if not isinstance(profile_ref, str) or not profile_ref.strip():
        return patch_dict, None

    ref = profile_ref.strip()
    cached = None if governance_profile_cache is None else governance_profile_cache.get(ref)
    if cached is None:
        try:
            cached = documents_module.resolve_governance_profile_ref(
                db=db,
                tenant_id=tenant_id,
                profile_ref=ref,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"Invalid governance_profile_ref: {str(exc)[:120]}") from exc
        if governance_profile_cache is not None:
            governance_profile_cache[ref] = cached
    patch_dict.update(dict(getattr(cached, "pipeline_patch", None) or {}))
    rules = getattr(cached, "regex_rules", None) or []
    if rules:
        patch_dict["governance_regex_rules"] = list(rules)
    return patch_dict, ref


def _apply_matched_rule_defaults(
    *,
    matched_rule: Any,
    parser_backend_choice: str,
    chunk_strategy_choice: str,
    default_parser_backend: str,
    default_chunk_strategy: str,
) -> tuple[str, str]:
    requested_pb = (parser_backend_choice or "").strip().lower()
    requested_cs = (chunk_strategy_choice or "").strip().lower()
    if requested_pb in {"", "auto", default_parser_backend} and getattr(matched_rule, "parser_backend", None):
        parser_backend_choice = str(matched_rule.parser_backend)
    if requested_cs in {"", default_chunk_strategy} and getattr(matched_rule, "chunk_strategy", None):
        chunk_strategy_choice = str(matched_rule.chunk_strategy)
    return parser_backend_choice, chunk_strategy_choice


def _build_ingestion_meta(
    *,
    policy: Any,
    matched_rule: Any,
    preprocess_steps: list[dict[str, Any]],
    governance_profile_ref: str | None,
) -> dict[str, Any]:
    return {
        "version": str(getattr(policy, "version", "1") if policy is not None else "1"),
        "rule": {"id": matched_rule.id, "name": matched_rule.name},
        "preprocess": {"enabled": bool(preprocess_steps), "steps": preprocess_steps},
        "governance_profile_ref": governance_profile_ref,
    }


def _resolve_parser_backend(
    *,
    file_ext: str,
    parser_backend_choice: str,
) -> str:
    from app.api.v1 import documents as documents_module

    requested_parser_backend = (parser_backend_choice or "").strip().lower()
    if file_ext == ".pdf" and requested_parser_backend in {"", "auto"}:
        return "auto"
    return documents_module.parser_factory.resolve_backend(file_ext, parser_backend_choice)


def _validate_pipeline_chunk_settings(
    *,
    dataset_meta: Any,
    pipeline_options: Any,
    resolved_chunk_strategy: str,
) -> None:
    from app.api.v1 import documents as documents_module

    pipeline_effective = documents_module.resolve_pipeline_effective(
        dataset_metadata=(dataset_meta or {}),
        document_metadata={},
        request_overrides=pipeline_options,
    )
    if resolved_chunk_strategy not in documents_module.chunker_factory.INTEGRATED_PIPELINE_STRATEGIES:
        documents_module._validate_chunk_params(
            pipeline_effective.chunk_size,
            pipeline_effective.chunk_overlap,
        )


def _resolve_upload_pipeline(
    *,
    db: Session,
    tenant_id: UUID,
    dataset_meta: Any,
    policy: Any,
    identity: _UploadIdentity,
    pipeline_parsed: Any,
    pipeline_overrides: Any,
    defaults: _UploadDefaultSelection,
    governance_profile_cache: dict[str, Any] | None = None,
) -> _ResolvedUploadPipeline:
    from app.api.v1 import documents as documents_module

    pipeline_options = documents_module._to_pipeline_options(
        pipeline=pipeline_parsed,
        overrides=pipeline_overrides,
    )
    matched_rule = documents_module.match_ingestion_rule(
        policy,
        filename=identity.upload_key or identity.filename,
        file_ext=identity.file_ext,
    )
    parser_backend_choice = defaults.parser_backend_base
    chunk_strategy_choice = defaults.chunk_strategy_base
    policy_patch = documents_module.PipelineOptions()
    ingestion_meta: dict[str, Any] | None = None
    if matched_rule is not None:
        parser_backend_choice, chunk_strategy_choice = _apply_matched_rule_defaults(
            matched_rule=matched_rule,
            parser_backend_choice=parser_backend_choice,
            chunk_strategy_choice=chunk_strategy_choice,
            default_parser_backend=defaults.default_parser_backend,
            default_chunk_strategy=defaults.default_chunk_strategy,
        )
        preprocess_steps = _serialize_preprocess_steps(matched_rule)
        patch_dict, governance_profile_ref = _resolve_governance_policy_patch(
            db=db,
            tenant_id=tenant_id,
            matched_rule=matched_rule,
            governance_profile_cache=governance_profile_cache,
        )
        if patch_dict:
            policy_patch = documents_module.PipelineOptions(**patch_dict)
        ingestion_meta = _build_ingestion_meta(
            policy=policy,
            matched_rule=matched_rule,
            preprocess_steps=preprocess_steps,
            governance_profile_ref=governance_profile_ref,
        )
    pipeline_options = documents_module.merge_pipeline_options(policy_patch, pipeline_options)
    resolved_parser_backend = _resolve_parser_backend(
        file_ext=identity.file_ext,
        parser_backend_choice=parser_backend_choice,
    )
    resolved_chunk_strategy = documents_module.chunker_factory.resolve_strategy(chunk_strategy_choice)
    _validate_pipeline_chunk_settings(
        dataset_meta=dataset_meta,
        pipeline_options=pipeline_options,
        resolved_chunk_strategy=resolved_chunk_strategy,
    )
    return _ResolvedUploadPipeline(
        pipeline_options=pipeline_options,
        ingestion_meta=ingestion_meta,
        resolved_parser_backend=resolved_parser_backend,
        resolved_chunk_strategy=resolved_chunk_strategy,
    )


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


def _parse_single_user_metadata(user_metadata: str | None) -> dict[str, Any] | None:
    if not isinstance(user_metadata, str) or not user_metadata.strip():
        return None
    raw = user_metadata.strip()
    max_len = int(settings.USER_METADATA_FORM_JSON_MAX_CHARS)
    if max_len > 0 and len(raw) > max_len:
        raise HTTPException(status_code=400, detail="user_metadata is too large")
    try:
        obj = json.loads(raw)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail="Invalid user_metadata JSON (expect UTF-8)") from exc
    if not isinstance(obj, dict):
        raise HTTPException(status_code=400, detail="user_metadata must be a JSON object")
    return obj


def _parse_batch_user_metadata_map(user_metadata_map: str | None) -> dict[str, dict[str, Any]]:
    from app.api.v1 import documents as documents_module

    user_meta_by_key: dict[str, dict[str, Any]] = {}
    if not isinstance(user_metadata_map, str) or not user_metadata_map.strip():
        return user_meta_by_key
    raw = user_metadata_map.strip()
    max_len = int(settings.USER_METADATA_MAP_FORM_JSON_MAX_CHARS)
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
        normalized = documents_module._normalize_upload_key(key)
        if normalized:
            user_meta_by_key[normalized] = value
    return user_meta_by_key


def _build_document_metadata(
    *,
    identity: _UploadIdentity,
    request_parser_backend: str,
    request_chunk_strategy: str,
    resolved_pipeline: _ResolvedUploadPipeline,
    file_sha256: str | None,
    user_patch: dict[str, Any] | None,
    upload_only: bool,
) -> _PreparedDocumentMetadata:
    from app.api.v1 import documents as documents_module

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
        documents_module.set_content_sha256(doc_metadata, file_sha256)
    documents_module.upsert_pipeline_metadata(doc_metadata, options=resolved_pipeline.pipeline_options)
    if resolved_pipeline.ingestion_meta:
        doc_metadata["ingestion"] = resolved_pipeline.ingestion_meta
    if isinstance(user_patch, dict) and user_patch:
        doc_metadata["user"] = documents_module._apply_user_metadata_patch(
            current={},
            patch=user_patch,
            replace=True,
        )
    if upload_only:
        doc_metadata["ingest_stage"] = "uploaded_only"
    pipeline_hash = documents_module._compute_pipeline_hash(doc_metadata)
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
    duplicate_document: Any,
    *,
    identity: _UploadIdentity,
    request_parser_backend: str,
    request_chunk_strategy: str,
    resolved_pipeline: _ResolvedUploadPipeline,
    pipeline_hash: str,
    file_sha256: str,
    user_patch: dict[str, Any] | None,
    ingest_lock: _IngestLockLease,
) -> dict[str, Any]:
    from app.api.v1 import documents as documents_module

    meta_any = dict(getattr(duplicate_document, "doc_metadata", None) or {})
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
    documents_module.upsert_pipeline_metadata(meta_any, options=resolved_pipeline.pipeline_options)
    if resolved_pipeline.ingestion_meta:
        meta_any["ingestion"] = resolved_pipeline.ingestion_meta
    if isinstance(user_patch, dict) and user_patch:
        current_user = meta_any.get("user") if isinstance(meta_any.get("user"), dict) else {}
        meta_any["user"] = documents_module._apply_user_metadata_patch(
            current=current_user,
            patch=user_patch,
            replace=False,
        )
    meta_any.setdefault("active_pipeline_hash", str(meta_any.get("pipeline_hash") or "").strip() or None)
    meta_any.setdefault(
        "active_pipeline_ready", bool(str(getattr(duplicate_document, "status", "") or "").lower() == "completed")
    )
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
    duplicate_document: Any,
    *,
    db: Session,
    identity: _UploadIdentity,
    request_parser_backend: str,
    request_chunk_strategy: str,
    resolved_pipeline: _ResolvedUploadPipeline,
    pipeline_hash: str,
    file_sha256: str,
    user_patch: dict[str, Any] | None,
    upload_only: bool,
    background_tasks: BackgroundTasks,
    tenant_id: UUID,
    account_id: str,
    ingest_lock: _IngestLockLease,
) -> Any:
    status0 = str(getattr(duplicate_document, "status", "") or "").lower()
    if status0 in {"pending", "processing"}:
        if _document_matches_dedup_identity(
            duplicate_document,
            file_sha256=file_sha256,
            pipeline_hash=pipeline_hash,
        ):
            return duplicate_document
        from app.api.v1 import documents as documents_module

        raise HTTPException(status_code=409, detail=documents_module.DUPLICATE_DOCUMENT_PROCESSING_DETAIL)
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
    from app.api.v1 import documents as documents_module

    await documents_module.retry_document_processing(
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


def _success_result(*, filename: str, source_path: str | None, document: Any) -> dict[str, Any]:
    return {"success": True, "filename": filename, **_document_result_snapshot(document, source_path=source_path)}


def _failure_result(*, filename: str, source_path: str | None, error: Any, limit: int = 200) -> dict[str, Any]:
    return {
        "success": False,
        "filename": filename or "unknown",
        "source_path": source_path,
        "error": str(error)[:limit] if error is not None else "upload_failed",
    }


def _coerce_batch_result(result: Any) -> dict[str, Any]:
    if isinstance(result, dict):
        return result
    if isinstance(result, Exception):
        return _failure_result(filename="unknown", source_path=None, error=result)
    return _failure_result(filename="unknown", source_path=None, error="upload_failed")


def _build_batch_response(
    *,
    files: list[UploadFile],
    successful: list[dict[str, Any]],
    failed: list[dict[str, Any]],
    precheck_scan_run_id: str | None = None,
) -> dict[str, Any]:
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
    return response


def _safe_staging_relpath(item: dict[str, Any], *, idx: int) -> Path:
    from app.api.v1 import documents as documents_module

    raw = str(item.get("upload_key") or item.get("filename") or f"FILE_{idx:06d}").strip()
    parts = documents_module._normalize_upload_path_parts(raw)
    if not parts:
        parts = [str(item.get("filename") or f"FILE_{idx:06d}")]
    safe_parts: list[str] = []
    for segment in parts:
        safe_segment = str(segment or "").replace("\\", "/").strip().rsplit("/", 1)[-1]
        safe_segment = "".join(ch for ch in safe_segment if ord(ch) >= 32 and ch != "\x7f")
        if not safe_segment or safe_segment in {".", ".."}:
            safe_segment = "item"
        safe_parts.append(safe_segment[:120] if len(safe_segment) > 120 else safe_segment)
    file_ext = str(item.get("file_ext") or "").strip().lower()
    if safe_parts and file_ext and not safe_parts[-1].lower().endswith(file_ext):
        safe_parts[-1] = f"{safe_parts[-1]}{file_ext}"
    relpath = Path(*safe_parts) if safe_parts else Path(f"FILE_{idx:06d}{file_ext}")
    return Path(*[part for part in relpath.parts if part not in {"", ".."}])


def _build_batch_document(
    documents_module: Any,
    *,
    file_id: UUID,
    tenant_id: UUID,
    dataset_id: UUID | None,
    identity: _UploadIdentity,
    file_size: int,
    stored_path: str,
    account_id: str,
    doc_metadata: dict[str, Any],
    file_sha256: str | None,
    pipeline_hash: str,
) -> Any:
    db_document = documents_module.DBDocument(
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
    if bool(getattr(settings, "UPLOAD_DEDUP_ENABLED", False)):
        db_document.dedup_key = _build_document_dedup_key(file_sha256=file_sha256, pipeline_hash=pipeline_hash)
    return db_document


async def _maybe_resolve_upload_duplicate(
    *,
    documents_module: Any,
    db: Session,
    background_tasks: BackgroundTasks,
    tenant_id: UUID,
    account_id: str,
    dataset_id: UUID | None,
    identity: _UploadIdentity,
    request_parser_backend: str,
    request_chunk_strategy: str,
    resolved_pipeline: _ResolvedUploadPipeline,
    pipeline_hash: str,
    file_sha256: str | None,
    user_patch: dict[str, Any] | None,
    upload_only: bool,
    file_path: Path,
    ingest_lock: _IngestLockLease,
    cleanup_exact_duplicate: bool,
) -> Any | None:
    if (
        not bool(getattr(settings, "UPLOAD_DEDUP_ENABLED", False))
        or not isinstance(file_sha256, str)
        or not file_sha256
    ):
        return None
    duplicate = documents_module._find_duplicate_document(
        db,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        file_sha256=file_sha256,
        pipeline_hash=pipeline_hash,
    )
    if duplicate is not None and str(getattr(duplicate, "status", "") or "").lower() not in {"failed"}:
        if cleanup_exact_duplicate:
            _unlink_upload(file_path)
        return duplicate
    duplicate_by_sha = documents_module._find_duplicate_document_by_sha(
        db,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        file_sha256=file_sha256,
    )
    if duplicate_by_sha is None:
        return None
    _unlink_upload(file_path)
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


def _apply_object_store_metadata_if_needed(doc_metadata: dict[str, Any], *, stored_path: str) -> None:
    if not is_object_storage_uri(stored_path):
        return
    store = get_document_object_store()
    if store is not None:
        doc_metadata.update(document_object_store_metadata(store))


async def _finalize_batch_document(
    *,
    background_tasks: BackgroundTasks,
    db: Session,
    document: Any,
    file_path: Path,
    pipeline_hash: str,
    resolved_pipeline: _ResolvedUploadPipeline,
    upload_only: bool,
    ingest_lock: _IngestLockLease,
) -> Any:
    if upload_only:
        with contextlib.suppress(Exception):
            reconcile_document_index_channels(
                db,
                document=document,
                pipeline_hash=pipeline_hash,
                reset_enabled_to_pending=True,
                commit=True,
            )
        if is_object_storage_uri(str(getattr(document, "file_path", "") or "")):
            _unlink_upload(file_path)
        return document
    with contextlib.suppress(Exception):
        reconcile_document_index_channels(
            db,
            document=document,
            pipeline_hash=pipeline_hash,
            reset_enabled_to_pending=True,
            commit=True,
        )
    keep_local_file = await _schedule_document_processing(
        background_tasks=background_tasks,
        file_path=file_path,
        document_id=document.id,
        tenant_id=document.tenant_id,
        account_id=str(getattr(document, "owner_id", "") or ""),
        pipeline_hash=pipeline_hash,
        parser_backend=resolved_pipeline.resolved_parser_backend,
        chunk_strategy=resolved_pipeline.resolved_chunk_strategy,
        db=db,
        db_document=document,
    )
    if not keep_local_file:
        _unlink_upload(file_path)
    _retain_ingest_lock_if_task_handed_off(document, ingest_lock=ingest_lock)
    return document


async def _process_saved_batch_upload(
    *,
    background_tasks: BackgroundTasks,
    documents_module: Any,
    db: Session,
    tenant_id: UUID,
    account_id: str,
    dataset: Any,
    dataset_meta: Any,
    policy: Any,
    pipeline_parsed: Any,
    pipeline_overrides: Any,
    defaults: _UploadDefaultSelection,
    identity: _UploadIdentity,
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
    ingest_lock = _IngestLockLease()
    prepared_metadata = _PreparedDocumentMetadata(doc_metadata={}, pipeline_hash="")
    stored_path: str | None = None
    persistence_started = False
    try:
        resolved_pipeline = _resolve_upload_pipeline(
            db=db,
            tenant_id=tenant_id,
            dataset_meta=dataset_meta,
            policy=policy,
            identity=identity,
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
            dataset_id=getattr(dataset, "id", None) if dataset is not None else None,
            file_sha256=file_sha256 if isinstance(file_sha256, str) else None,
            pipeline_hash=prepared_metadata.pipeline_hash,
            account_id=account_id,
            doc_metadata=prepared_metadata.doc_metadata,
            ingest_lock=ingest_lock,
        )
        duplicate = await _maybe_resolve_upload_duplicate(
            documents_module=documents_module,
            db=db,
            background_tasks=background_tasks,
            tenant_id=tenant_id,
            account_id=account_id,
            dataset_id=getattr(dataset, "id", None) if dataset is not None else None,
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
        stored_path = await _store_document_source(
            file_path=file_path,
            tenant_id=tenant_id,
            dataset_id=dataset.id if dataset is not None else tenant_id,
            document_id=file_id,
            extension=identity.file_ext,
            content_type=content_type,
        )
        _apply_object_store_metadata_if_needed(prepared_metadata.doc_metadata, stored_path=stored_path)
        db_document = _build_batch_document(
            documents_module,
            file_id=file_id,
            tenant_id=tenant_id,
            dataset_id=getattr(dataset, "id", None) if dataset is not None else None,
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
            await _persist_uploaded_document(db, db_document, file_path=file_path)
        except _DuplicatePersistedDocumentError as exc:
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
            await _cleanup_unpersisted_source(stored_path, document_metadata=prepared_metadata.doc_metadata)
        if not persistence_started or is_object_storage_uri(stored_path or ""):
            _unlink_upload(file_path)
        logger.error("Error processing file %s: %s", identity.filename, str(exc)[:200])
        return _failure_result(filename=identity.filename, source_path=identity.source_path, error=exc)
    finally:
        await ingest_lock.cleanup()
        with contextlib.suppress(Exception):
            db.close()


async def _process_live_batch_upload(
    *,
    background_tasks: BackgroundTasks,
    documents_module: Any,
    db: Session,
    tenant_id: UUID,
    account_id: str,
    dataset: Any,
    dataset_meta: Any,
    policy: Any,
    pipeline_parsed: Any,
    pipeline_overrides: Any,
    defaults: _UploadDefaultSelection,
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
        file_size, file_sha256 = await documents_module.save_upload_file_with_hash(
            file,
            file_path,
            max_bytes=settings.MAX_FILE_SIZE,
        )
        from app.services.tenant_quota_service import enforce_tenant_upload_quotas

        try:
            enforce_tenant_upload_quotas(
                db,
                tenant_id=tenant_id,
                additional_docs=1,
                additional_bytes=int(file_size or 0),
            )
        except HTTPException as exc:
            _unlink_upload(file_path)
            return _failure_result(
                filename=identity.filename,
                source_path=identity.source_path,
                error=str(getattr(exc, "detail", "") or "tenant_quota_exceeded"),
            )
        return await _process_saved_batch_upload(
            background_tasks=background_tasks,
            documents_module=documents_module,
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
            file_size=int(file_size or 0),
            file_sha256=str(file_sha256 or "").strip().lower() or None,
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


async def _stage_upload_for_precheck(
    file: UploadFile,
    *,
    tenant_id: UUID,
) -> dict[str, Any]:
    from app.api.v1 import documents as documents_module

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
        file_size, file_sha256 = await documents_module.save_upload_file_with_hash(
            file,
            file_path,
            max_bytes=settings.MAX_FILE_SIZE,
        )
    except HTTPException as exc:
        _unlink_upload(file_path)
        return _failure_result(
            filename=identity.filename,
            source_path=identity.source_path,
            error=str(getattr(exc, "detail", "") or str(exc) or "upload_failed"),
        )
    except asyncio.CancelledError:
        _unlink_upload(file_path)
        raise
    except Exception as exc:  # noqa: BLE001
        _unlink_upload(file_path)
        return _failure_result(filename=identity.filename, source_path=identity.source_path, error=exc)
    return {
        "success": True,
        "filename": identity.filename,
        "source_path": identity.source_path,
        "upload_key": identity.upload_key,
        "file_ext": identity.file_ext,
        "file_id": file_id,
        "file_path": str(file_path),
        "file_size": int(file_size or 0),
        "file_sha256": str(file_sha256 or "").strip().lower() or None,
        "content_type": file.content_type or "application/octet-stream",
    }


def _partition_batch_results(results: list[Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    processed = [_coerce_batch_result(result) for result in results]
    return [result for result in processed if result.get("success")], [
        result for result in processed if not result.get("success")
    ]


def _cleanup_uploaded_batch_files(results: list[dict[str, Any]]) -> None:
    for result in results:
        _unlink_upload(Path(str(result.get("file_path") or "")))


def _link_precheck_staging_tree(staged_successful: list[dict[str, Any]], *, staging_root: Path) -> bool:
    from app.api.v1 import documents as documents_module

    linked_any = False
    staging_root_resolved = staging_root.resolve(strict=False)
    for idx, item in enumerate(staged_successful):
        src_raw = str(item.get("file_path") or "").strip()
        if not src_raw:
            continue
        src = Path(src_raw).resolve(strict=False)
        if not src.exists() or not src.is_file():
            continue
        dst = (staging_root / _safe_staging_relpath(item, idx=idx)).resolve(strict=False)
        try:
            dst.relative_to(staging_root_resolved)
        except Exception:
            dst = (staging_root / f"FILE_{idx:06d}{str(item.get('file_ext') or '').strip().lower()}").resolve(
                strict=False
            )
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.exists():
            suffix = getattr(item.get("file_id"), "hex", None) or uuid.uuid4().hex
            dst = dst.with_name(f"{dst.stem}.{suffix}{dst.suffix}")
        try:
            documents_module.os.link(src, dst)
            linked_any = True
        except Exception:
            try:
                documents_module.shutil.copy2(src, dst)
                linked_any = True
            except Exception:
                logger.debug("Skipping item after non-critical exception", exc_info=True)
    return linked_any


async def _run_precheck_scan(
    *,
    documents_module: Any,
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
        scan_run = documents_module.DBDatasetPrecheckScanRun(
            tenant_id=tenant_id,
            dataset_id=dataset.id,
            requested_by=account_id,
            kind="path",
            status="pending",
            progress=0,
            config={
                "root_path": str(staging_root),
                "max_files": int(len(staged_successful)),
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
        db.add(scan_run)
        db.commit()
        db.refresh(scan_run)
        await asyncio.to_thread(
            _run_precheck_scan_job,
            documents_module,
            tenant_id=tenant_id,
            dataset_id=dataset.id,
            scan_run_id=scan_run.id,
        )
        with contextlib.suppress(Exception):
            db.refresh(scan_run)
        if not precheck_only:
            _apply_precheck_policy_suggestion(
                documents_module,
                db=db,
                dataset=dataset,
                scan_run=scan_run,
                tenant_id=tenant_id,
            )
        return scan_run
    except Exception as exc:  # noqa: BLE001
        logger.warning("Precheck-first ingest failed; continuing without precheck: %s", str(exc)[:200])
        return scan_run
    finally:
        with contextlib.suppress(Exception):
            documents_module.shutil.rmtree(staging_root)


def _run_precheck_scan_job(
    documents_module: Any,
    *,
    tenant_id: UUID,
    dataset_id: UUID,
    scan_run_id: UUID,
) -> None:
    db2 = documents_module.SessionLocal()
    try:
        documents_module.run_dataset_precheck_scan(
            db2,
            tenant_id=tenant_id,
            dataset_id=dataset_id,
            scan_run_id=scan_run_id,
        )
    except Exception as exc:  # noqa: BLE001
        try:
            row = (
                db2.query(documents_module.DBDatasetPrecheckScanRun)
                .filter(
                    documents_module.DBDatasetPrecheckScanRun.id == scan_run_id,
                    documents_module.DBDatasetPrecheckScanRun.tenant_id == tenant_id,
                    documents_module.DBDatasetPrecheckScanRun.dataset_id == dataset_id,
                )
                .first()
            )
            if row is not None:
                row.status = "failed"
                row.error_message = str(exc)[:200]
                row.finished_at = datetime.now(UTC)
                db2.commit()
        except Exception as mark_exc:  # noqa: BLE001
            documents_module.logger.warning(
                "Failed to mark precheck scan run as failed: %s",
                str(mark_exc)[:200],
            )
        raise
    finally:
        db2.close()


def _apply_precheck_policy_suggestion(
    documents_module: Any,
    *,
    db: Session,
    dataset: Any,
    scan_run: Any,
    tenant_id: UUID,
) -> None:
    try:
        documents_module.apply_ingestion_policy_suggestion(
            db,
            dataset=dataset,
            scan_run=scan_run,
            tenant_id=tenant_id,
            replace=False,
        )
    except HTTPException as exc:
        if int(getattr(exc, "status_code", 0) or 0) != 409:
            documents_module.logger.warning(
                "Precheck-first policy apply failed: %s",
                str(getattr(exc, "detail", exc))[:200],
            )
    except Exception as exc:  # noqa: BLE001
        documents_module.logger.warning("Precheck-first policy apply failed: %s", str(exc)[:200])


def _refresh_batch_policy(documents_module: Any, dataset: Any) -> Any:
    dataset_meta = (getattr(dataset, "dataset_metadata", None) or {}) if dataset is not None else {}
    return documents_module.parse_ingestion_policy_from_metadata(dataset_meta if isinstance(dataset_meta, dict) else {})  # type: ignore[arg-type]


def _finalize_batch_ingestion_run(
    *,
    documents_module: Any,
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
        doc_id_raw = str(result.get("document_id") or "").strip()
        if not doc_id_raw:
            continue
        try:
            doc_id = UUID(doc_id_raw)
        except ValueError:
            continue
        doc = (
            db.query(documents_module.DBDocument)
            .filter(
                documents_module.DBDocument.id == doc_id,
                documents_module.DBDocument.tenant_id == tenant_id,
            )
            .first()
        )
        if doc is None:
            continue
        try:
            meta0 = dict(getattr(doc, "doc_metadata", None) or {})
            meta0["last_ingestion_run_id"] = str(ingestion_run.id)
            meta0["last_ingestion_kind"] = "upload_batch"
            doc.doc_metadata = meta0
            db.commit()
            db.refresh(doc)
        except Exception:
            meta0 = dict(getattr(doc, "doc_metadata", None) or {})
        with contextlib.suppress(Exception):
            documents_module.IngestionRunService.add_document(
                db,
                tenant_id=tenant_id,
                run_id=ingestion_run.id,
                document_id=doc.id,
                source_ref=(result.get("source_path") or getattr(doc, "filename", None)),
                initial_status=str(result.get("status") or getattr(doc, "status", "") or "created"),
                doc_meta=meta0 if isinstance(meta0, dict) else None,
            )
    with contextlib.suppress(Exception):
        documents_module.IngestionRunService.close_intake(
            db,
            tenant_id=tenant_id,
            run_id=ingestion_run.id,
            attempted_inputs=int(len(files or [])),
            rejected_inputs=int(len(failed)),
            rejection_reasons=[result.get("error") for result in failed],
        )


def _validate_batch_upload_request(files: list[UploadFile], *, max_concurrent: int) -> int:
    if not files:
        raise HTTPException(status_code=400, detail="No files provided")
    if len(files) > 50:
        raise HTTPException(status_code=400, detail="Too many files. Maximum 50 files per batch.")
    max_concurrent_raw = int(max_concurrent or 0)
    if max_concurrent_raw <= 0:
        raise HTTPException(status_code=400, detail="max_concurrent must be at least 1")
    return min(max_concurrent_raw, 10)


def _create_single_ingestion_run(
    *,
    documents_module: Any,
    db: Session,
    tenant_id: UUID,
    dataset_id: UUID | None,
    account_id: str,
    identity: _UploadIdentity,
    parser_backend: str,
    chunk_strategy: str,
    resolved_pipeline: _ResolvedUploadPipeline,
    pipeline_hash: str,
    pipeline_parsed: Any,
) -> Any:
    try:
        return documents_module.IngestionRunService.create_run(
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
    documents_module: Any,
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
        meta0 = dict(getattr(document, "doc_metadata", None) or {})
        if created and not meta0.get("created_by_run_id"):
            meta0["created_by_run_id"] = str(ingestion_run.id)
        meta0["last_ingestion_run_id"] = str(ingestion_run.id)
        meta0["last_ingestion_kind"] = "upload"
        document.doc_metadata = meta0
        db.commit()
        db.refresh(document)
    except Exception:
        meta0 = dict(getattr(document, "doc_metadata", None) or {})
    with contextlib.suppress(Exception):
        documents_module.IngestionRunService.add_document(
            db,
            tenant_id=tenant_id,
            run_id=ingestion_run.id,
            document_id=document.id,
            source_ref=(identity.source_path or document.filename),
            initial_status=str(getattr(document, "status", "") or "created"),
            doc_meta=meta0 if isinstance(meta0, dict) else None,
        )


async def _maybe_resolve_single_upload_duplicate(
    *,
    documents_module: Any,
    db: Session,
    background_tasks: BackgroundTasks,
    tenant_id: UUID,
    account_id: str,
    dataset_id: UUID | None,
    identity: _UploadIdentity,
    request_parser_backend: str,
    request_chunk_strategy: str,
    resolved_pipeline: _ResolvedUploadPipeline,
    pipeline_hash: str,
    file_sha256: str | None,
    user_patch: dict[str, Any] | None,
    ingest_lock: _IngestLockLease,
) -> Any | None:
    if (
        not bool(getattr(settings, "UPLOAD_DEDUP_ENABLED", False))
        or not isinstance(file_sha256, str)
        or not file_sha256
    ):
        return None
    duplicate = documents_module._find_duplicate_document(
        db,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        file_sha256=file_sha256,
        pipeline_hash=pipeline_hash,
    )
    if duplicate is not None and str(getattr(duplicate, "status", "") or "").lower() not in {"failed"}:
        documents_module.logger.info(
            "Upload dedup hit tenant_id=%s dataset_id=%s document_id=%s",
            str(tenant_id),
            str(dataset_id),
            str(getattr(duplicate, "id", "")),
        )
        return duplicate
    duplicate_by_sha = documents_module._find_duplicate_document_by_sha(
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


@dataclass
class PipelineOverridesFormFields:
    governance_enabled: bool | None = Form(None)
    governance_remove_toc_lines: bool | None = Form(None)
    governance_remove_noise_lines: bool | None = Form(None)
    governance_unwrap_lines: bool | None = Form(None)
    governance_remove_common_lines: bool | None = Form(None)
    governance_unwrap_max_line_length: int | None = Form(None)
    governance_noise_min_chars: int | None = Form(None)
    governance_noise_ratio_threshold: float | None = Form(None)
    governance_common_lines_min_docs: int | None = Form(None)
    governance_common_lines_min_ratio: float | None = Form(None)
    chunk_size: int | None = Form(None)
    chunk_overlap: int | None = Form(None)
    chunk_vector_enabled: bool | None = Form(None)
    bm25_index_enabled: bool | None = Form(None)
    kg_enabled: bool | None = Form(None)
    event_vector_enabled: bool | None = Form(None)
    entity_vector_enabled: bool | None = Form(None)


@dataclass
class UploadDocumentFormFields:
    parser_backend: str = Form(settings.DEFAULT_PARSER_BACKEND)
    chunk_strategy: str = Form(settings.DEFAULT_CHUNK_STRATEGY)
    pipeline: str | None = Form(None)
    dataset_id: UUID | None = Form(None)
    user_metadata: str | None = Form(None)


@dataclass
class UploadDocumentsBatchFormFields:
    parser_backend: str = Form(settings.DEFAULT_PARSER_BACKEND)
    chunk_strategy: str = Form(settings.DEFAULT_CHUNK_STRATEGY)
    pipeline: str | None = Form(None)
    dataset_id: UUID | None = Form(None)
    precheck_first: bool = Form(False)
    precheck_only: bool = Form(False)
    upload_only: bool = Form(False)
    user_metadata_map: str | None = Form(None)
    max_concurrent: int = Form(5)


@router.post("/upload", response_model=DocumentDetail, status_code=201, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def upload_document(
    background_tasks: BackgroundTasks,
    file: Annotated[UploadFile, File(...)],
    form: Annotated[UploadDocumentFormFields, Depends()],
    overrides_form: Annotated[PipelineOverridesFormFields, Depends()],
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    file_lease = _UploadFileLease()
    try:
        return await _upload_document_impl(
            background_tasks,
            file,
            form,
            overrides_form,
            tenant_id=tenant_id,
            account_id=account_id,
            db=db,
            file_lease=file_lease,
        )
    finally:
        file_lease.cleanup()


async def _upload_document_impl(
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
    from app.api.v1 import documents as documents_module  # Local import to avoid router circular import.

    ingest_lock = _IngestLockLease()
    identity = _normalize_upload_identity(file)
    _require_upload_extension(identity.file_ext)
    parser_backend = form.parser_backend
    chunk_strategy = form.chunk_strategy
    dataset = documents_module._resolve_writable_dataset(db, tenant_id, account_id, form.dataset_id)
    dataset_meta = (getattr(dataset, "dataset_metadata", None) or {}) if dataset is not None else {}
    policy = documents_module.parse_ingestion_policy_from_metadata(
        dataset_meta if isinstance(dataset_meta, dict) else {}
    )  # type: ignore[arg-type]
    pipeline_parsed = documents_module._parse_pipeline_json(form.pipeline)
    pipeline_overrides = documents_module.PipelineOptionOverrides(**asdict(overrides_form))
    dataset_default_pb, dataset_default_cs = _dataset_upload_defaults(dataset_meta)
    defaults = _select_upload_defaults(
        parser_backend=parser_backend,
        chunk_strategy=chunk_strategy,
        dataset_default_pb=dataset_default_pb,
        dataset_default_cs=dataset_default_cs,
    )
    resolved_pipeline = _resolve_upload_pipeline(
        db=db,
        tenant_id=tenant_id,
        dataset_meta=dataset_meta,
        policy=policy,
        identity=identity,
        pipeline_parsed=pipeline_parsed,
        pipeline_overrides=pipeline_overrides,
        defaults=defaults,
    )
    file_id = uuid.uuid4()
    file_path = _document_upload_path(tenant_id, file_id, identity.file_ext)
    file_lease.acquire(file_path)

    file_size, file_sha256 = await documents_module.save_upload_file_with_hash(
        file, file_path, max_bytes=settings.MAX_FILE_SIZE
    )

    from app.services.tenant_quota_service import enforce_tenant_upload_quotas

    enforce_tenant_upload_quotas(
        db,
        tenant_id=tenant_id,
        additional_docs=1,
        additional_bytes=int(file_size or 0),
    )
    user_patch = _parse_single_user_metadata(form.user_metadata)
    prepared_metadata = _build_document_metadata(
        identity=identity,
        request_parser_backend=parser_backend,
        request_chunk_strategy=chunk_strategy,
        resolved_pipeline=resolved_pipeline,
        file_sha256=file_sha256 if isinstance(file_sha256, str) else None,
        user_patch=user_patch,
        upload_only=False,
    )
    doc_metadata = prepared_metadata.doc_metadata
    pipeline_hash = prepared_metadata.pipeline_hash

    await _maybe_acquire_ingest_lock(
        tenant_id=tenant_id,
        dataset_id=getattr(dataset, "id", None),
        file_sha256=file_sha256 if isinstance(file_sha256, str) else None,
        pipeline_hash=pipeline_hash,
        account_id=account_id,
        doc_metadata=doc_metadata,
        ingest_lock=ingest_lock,
    )

    try:
        ingestion_run = _create_single_ingestion_run(
            documents_module=documents_module,
            db=db,
            tenant_id=tenant_id,
            dataset_id=getattr(dataset, "id", None),
            account_id=account_id,
            identity=identity,
            parser_backend=parser_backend,
            chunk_strategy=chunk_strategy,
            resolved_pipeline=resolved_pipeline,
            pipeline_hash=pipeline_hash,
            pipeline_parsed=pipeline_parsed,
        )
        duplicate = await _maybe_resolve_single_upload_duplicate(
            documents_module=documents_module,
            db=db,
            background_tasks=background_tasks,
            tenant_id=tenant_id,
            account_id=account_id,
            dataset_id=getattr(dataset, "id", None),
            identity=identity,
            request_parser_backend=parser_backend,
            request_chunk_strategy=chunk_strategy,
            resolved_pipeline=resolved_pipeline,
            pipeline_hash=pipeline_hash,
            file_sha256=file_sha256 if isinstance(file_sha256, str) else None,
            user_patch=user_patch,
            ingest_lock=ingest_lock,
        )
        if duplicate is not None:
            with contextlib.suppress(Exception):
                _attach_document_to_ingestion_run(
                    documents_module=documents_module,
                    db=db,
                    ingestion_run=ingestion_run,
                    tenant_id=tenant_id,
                    identity=identity,
                    document=duplicate,
                    created=False,
                )
            return duplicate

        stored_path = await _store_document_source(
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
            db_document = documents_module.DBDocument(
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
            if bool(getattr(settings, "UPLOAD_DEDUP_ENABLED", False)):
                db_document.dedup_key = _build_document_dedup_key(file_sha256=file_sha256, pipeline_hash=pipeline_hash)
            persistence_started = True
            await _persist_uploaded_document(db, db_document, file_path=file_path)
        except _DuplicatePersistedDocumentError as exc:
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
                    documents_module=documents_module,
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
                await _cleanup_unpersisted_source(stored_path, document_metadata=doc_metadata)
            raise
        with contextlib.suppress(Exception):
            _attach_document_to_ingestion_run(
                documents_module=documents_module,
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

        keep_local_file = await _schedule_document_processing(
            background_tasks=background_tasks,
            file_path=file_path,
            document_id=file_id,
            tenant_id=tenant_id,
            account_id=account_id,
            pipeline_hash=pipeline_hash,
            parser_backend=resolved_pipeline.resolved_parser_backend,
            chunk_strategy=resolved_pipeline.resolved_chunk_strategy,
            db=db,
            db_document=db_document,
        )
        if keep_local_file:
            file_lease.transfer()
        _retain_ingest_lock_if_task_handed_off(db_document, ingest_lock=ingest_lock)

        return db_document
    finally:
        await ingest_lock.cleanup()


@router.post("/upload-url", response_model=DocumentDetail, status_code=201, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def upload_document_from_url(
    background_tasks: BackgroundTasks,
    body: UrlUploadRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Fetch a remote URL and ingest it as a document.

    Notes:
    - Disabled by default: set URL_INGEST_ENABLED=true to enable.
    - SSRF guard: blocks private/loopback/link-local hosts by default.
    """
    from app.api.v1 import documents as documents_module  # Local import to avoid router circular import.

    return await documents_module._ingest_url_upload_request(
        background_tasks=background_tasks,
        body=body,
        tenant_id=tenant_id,
        account_id=account_id,
        db=db,
        ingestion_kind="upload_url",
    )


@router.post(
    "/upload-batch",
    response_model=DocumentBatchUploadResponse,
    status_code=201,
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
async def upload_documents_batch(
    background_tasks: BackgroundTasks,
    files: Annotated[list[UploadFile], File(...)],
    form: Annotated[UploadDocumentsBatchFormFields, Depends()],
    overrides_form: Annotated[PipelineOverridesFormFields, Depends()],
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    from app.api.v1 import documents as documents_module  # Local import to avoid router circular import.
    from app.services.tenant_quota_service import enforce_tenant_upload_quotas

    max_concurrent = _validate_batch_upload_request(files, max_concurrent=form.max_concurrent)
    enforce_tenant_upload_quotas(
        db,
        tenant_id=tenant_id,
        additional_docs=int(len(files or [])),
        additional_bytes=0,
    )

    pipeline_overrides = documents_module.PipelineOptionOverrides(**asdict(overrides_form))
    parser_backend = form.parser_backend
    chunk_strategy = form.chunk_strategy
    precheck_first = form.precheck_first
    precheck_only = form.precheck_only
    upload_only = form.upload_only
    pipeline_parsed = documents_module._parse_pipeline_json(form.pipeline)
    user_meta_by_key = _parse_batch_user_metadata_map(form.user_metadata_map)
    dataset = documents_module._resolve_writable_dataset(db, tenant_id, account_id, form.dataset_id)
    dataset_meta = (getattr(dataset, "dataset_metadata", None) or {}) if dataset is not None else {}
    policy = _refresh_batch_policy(documents_module, dataset)
    dataset_default_pb, dataset_default_cs = _dataset_upload_defaults(dataset_meta)
    defaults = _select_upload_defaults(
        parser_backend=parser_backend,
        chunk_strategy=chunk_strategy,
        dataset_default_pb=dataset_default_pb,
        dataset_default_cs=dataset_default_cs,
    )
    ingestion_run = None
    if not precheck_only and not upload_only:
        try:
            ingestion_run = documents_module.IngestionRunService.create_run(
                db,
                tenant_id=tenant_id,
                dataset_id=getattr(dataset, "id", None),
                requested_by=account_id,
                kind="upload_batch",
                config={
                    "files": int(len(files or [])),
                    "parser_backend_requested": str(parser_backend or "")[:80],
                    "chunk_strategy_requested": str(chunk_strategy or "")[:80],
                    "pipeline": (
                        pipeline_parsed.model_dump(exclude_none=True) if pipeline_parsed is not None else None
                    ),
                },
                expected_documents=int(len(files or [])),
            )
        except Exception:
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
            total_bytes = sum(int(result.get("file_size") or 0) for result in staged_successful)
            enforce_tenant_upload_quotas(
                db,
                tenant_id=tenant_id,
                additional_docs=int(len(staged_successful)),
                additional_bytes=int(total_bytes),
            )
        except HTTPException:
            _cleanup_uploaded_batch_files(staged_successful)
            raise
        scan_run = None
        if staged_successful:
            scan_run = await _run_precheck_scan(
                documents_module=documents_module,
                db=db,
                tenant_id=tenant_id,
                account_id=account_id,
                dataset=dataset,
                staged_successful=staged_successful,
                precheck_only=precheck_only,
            )
        if not precheck_only and dataset is not None:
            with contextlib.suppress(Exception):
                db.refresh(dataset)
            dataset_meta = (getattr(dataset, "dataset_metadata", None) or {}) if dataset is not None else {}
            policy = _refresh_batch_policy(documents_module, dataset)
            dataset_default_pb, dataset_default_cs = _dataset_upload_defaults(dataset_meta)
            defaults = _select_upload_defaults(
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
                    documents_module=documents_module,
                    db=documents_module.SessionLocal(),
                    tenant_id=tenant_id,
                    account_id=account_id,
                    dataset=dataset,
                    dataset_meta=dataset_meta,
                    policy=policy,
                    pipeline_parsed=pipeline_parsed,
                    pipeline_overrides=pipeline_overrides,
                    defaults=defaults,
                    identity=_UploadIdentity(
                        filename=str(staged.get("filename") or "unknown"),
                        file_ext=str(staged.get("file_ext") or "").strip().lower()
                        or Path(str(staged.get("filename") or "unknown")).suffix.lower(),
                        upload_key=str(staged.get("upload_key") or ""),
                        source_path=staged.get("source_path"),
                    ),
                    file_id=staged.get("file_id"),
                    file_path=Path(str(staged.get("file_path") or "")),
                    file_size=int(staged.get("file_size") or 0),
                    file_sha256=staged.get("file_sha256"),
                    content_type=str(staged.get("content_type") or "application/octet-stream"),
                    request_parser_backend=parser_backend,
                    request_chunk_strategy=chunk_strategy,
                    user_patch=_select_upload_user_patch(
                        user_meta_by_key=user_meta_by_key,
                        upload_key=str(staged.get("upload_key") or ""),
                        filename=str(staged.get("filename") or "unknown"),
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
            documents_module=documents_module,
            db=db,
            tenant_id=tenant_id,
            ingestion_run=ingestion_run,
            files=files,
            successful=successful,
            failed=failed,
        )
        return _build_batch_response(files=files, successful=successful, failed=failed)

    governance_profile_cache: dict[str, Any] = {}
    direct_results = await _gather_with_concurrency_limit(
        [
            lambda file=file: _process_live_batch_upload(
                background_tasks=background_tasks,
                documents_module=documents_module,
                db=documents_module.SessionLocal(),
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
        documents_module=documents_module,
        db=db,
        tenant_id=tenant_id,
        ingestion_run=ingestion_run,
        files=files,
        successful=successful,
        failed=failed,
    )
    return _build_batch_response(files=files, successful=successful, failed=failed)

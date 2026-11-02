"""Source persistence, document identity lookup and ambiguous commit ownership."""

import asyncio
import contextlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Query, Session

from app.core.async_bridge import run_blocking_in_thread
from app.core.database import SessionLocal
from app.models.document import Document as DBDocument
from app.rag.core.logging import get_logger
from app.services.document_identity import build_document_dedup_key, get_content_sha256
from app.storage.object.minio import MinIOService
from app.storage.object.runtime import (
    ObjectStorageRef,
    get_document_object_store,
    get_object_store_for_uri,
    is_object_storage_uri,
    object_store_backend_config,
    parse_object_storage_uri,
)

logger = get_logger("services.document_source_persistence")
DOCUMENT_DEDUP_CONSTRAINT_NAME = "uq_documents_tenant_dataset_dedup_key_active"


class DuplicatePersistedDocumentError(RuntimeError):
    def __init__(self, document: DBDocument) -> None:
        super().__init__("duplicate persisted document")
        self.document = document


@dataclass
class SourceFileLease:
    path: Path
    owned: bool = True
    stored_path: str | None = None
    document_metadata: dict[str, Any] | None = None

    def transfer(self) -> None:
        self.owned = False

    def set_stored_source(self, stored_path: str, *, document_metadata: dict[str, Any] | None = None) -> None:
        self.stored_path = stored_path
        self.document_metadata = document_metadata

    def cleanup(self) -> None:
        if self.owned:
            unlink_source(self.path)

    async def cleanup_source(self) -> None:
        if not self.owned:
            return
        if self.stored_path is not None:
            await cleanup_unpersisted_source(self.stored_path, document_metadata=self.document_metadata)
        unlink_source(self.path)


def unlink_source(path: Path) -> None:
    with contextlib.suppress(OSError):
        path.unlink(missing_ok=True)


def _duplicate_document_query(db: Session, *, tenant_id: UUID, dataset_id: UUID) -> Query[DBDocument]:
    return (
        db.query(DBDocument)
        .filter(
            DBDocument.tenant_id == tenant_id,
            DBDocument.dataset_id == dataset_id,
            DBDocument.archived_at.is_(None),
        )
        .order_by(DBDocument.updated_at.desc(), DBDocument.created_at.desc())
    )


def find_duplicate_document(
    db: Session,
    *,
    tenant_id: UUID,
    dataset_id: UUID | None,
    file_sha256: str,
    pipeline_hash: str,
) -> DBDocument | None:
    if dataset_id is None:
        return None
    return (
        _duplicate_document_query(db, tenant_id=tenant_id, dataset_id=dataset_id)
        .filter(
            (DBDocument.doc_metadata["content_sha256"].astext == file_sha256)
            | (DBDocument.doc_metadata["file_sha256"].astext == file_sha256)
        )
        .filter(DBDocument.doc_metadata["pipeline_hash"].astext == pipeline_hash)
        .first()
    )


def find_duplicate_document_by_sha(
    db: Session,
    *,
    tenant_id: UUID,
    dataset_id: UUID | None,
    file_sha256: str,
) -> DBDocument | None:
    if dataset_id is None:
        return None
    return (
        _duplicate_document_query(db, tenant_id=tenant_id, dataset_id=dataset_id)
        .filter(
            (DBDocument.doc_metadata["content_sha256"].astext == file_sha256)
            | (DBDocument.doc_metadata["file_sha256"].astext == file_sha256)
        )
        .first()
    )


def document_matches_dedup_identity(document: DBDocument, *, file_sha256: str, pipeline_hash: str) -> bool:
    expected = build_document_dedup_key(content_sha256=file_sha256, pipeline_hash=pipeline_hash)
    if expected and document.dedup_key == expected:
        return True
    metadata = document.doc_metadata or {}
    return get_content_sha256(metadata) == file_sha256 and metadata.get("pipeline_hash") == pipeline_hash


def is_document_dedup_integrity_error(exc: IntegrityError) -> bool:
    # Driver error shapes are external data; psycopg exposes the constraint in
    # diag, while other supported drivers include it in their message.
    diag = getattr(getattr(exc, "orig", None), "diag", None)
    if getattr(diag, "constraint_name", None) == DOCUMENT_DEDUP_CONSTRAINT_NAME:
        return True
    return DOCUMENT_DEDUP_CONSTRAINT_NAME in str(getattr(exc, "orig", None) or exc)


async def store_document_source(
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
    uploaded_path: str | None = None

    def upload() -> str:
        nonlocal uploaded_path
        uploaded_path = store.upload_document_file(
            file_path=file_path,
            tenant_id=str(tenant_id),
            dataset_id=str(dataset_id),
            document_id=str(document_id),
            extension=extension,
            content_type=content_type,
        )
        return uploaded_path

    try:
        return await run_blocking_in_thread(upload, on_cancelled_worker_error=_log_cancelled_storage_error)
    except asyncio.CancelledError:
        try:
            if uploaded_path is not None:
                await _cleanup_unpersisted_store_object(store=store, reference=parse_object_storage_uri(uploaded_path))
        finally:
            unlink_source(file_path)
        raise
    except Exception:
        unlink_source(file_path)
        raise


def _log_cancelled_storage_error(exc: BaseException) -> None:
    logger.warning(
        "Object storage work failed after request cancellation", exc_info=(type(exc), exc, exc.__traceback__)
    )


async def _cleanup_unpersisted_store_object(*, store: MinIOService, reference: ObjectStorageRef) -> None:
    try:
        backend = object_store_backend_config(store)
        if reference.bucket != str(backend.get("bucket", "") or "").strip():
            return
        await run_blocking_in_thread(
            store.delete_object,
            object_name=reference.object_name,
            on_cancelled_worker_error=_log_cancelled_storage_error,
        )
    except Exception as exc:
        logger.warning("Failed to delete unpersisted document object: %s", str(exc)[:200])


async def cleanup_unpersisted_source(stored_path: str, *, document_metadata: dict[str, Any] | None = None) -> None:
    if not is_object_storage_uri(stored_path):
        return
    try:
        ref = parse_object_storage_uri(stored_path)
        store = get_object_store_for_uri(stored_path, document_metadata=document_metadata)
        await _cleanup_unpersisted_store_object(store=store, reference=ref)
    except Exception as exc:
        logger.warning("Failed to delete unpersisted document object: %s", str(exc)[:200])


def _fresh_session_document_exists(*, document_id: UUID) -> bool | None:
    """None means verification failed, so deleting the source would lose data."""
    try:
        check_db = SessionLocal()
    except Exception as exc:
        logger.warning("Failed to open verification session after commit error: %s", str(exc)[:200])
        return None
    try:
        return check_db.get(DBDocument, document_id) is not None
    except Exception as exc:
        logger.warning("Failed to verify document existence after commit error: %s", str(exc)[:200])
        return None
    finally:
        with contextlib.suppress(Exception):
            check_db.close()


async def cleanup_commit_ambiguous_source(
    *,
    document_id: UUID,
    stored_path: str,
    file_path: Path,
    document_metadata: dict[str, Any] | None = None,
) -> None:
    document_exists = _fresh_session_document_exists(document_id=document_id)
    if document_exists is False:
        await cleanup_unpersisted_source(stored_path, document_metadata=document_metadata)
        unlink_source(file_path)
    elif is_object_storage_uri(stored_path):
        unlink_source(file_path)


async def persist_uploaded_document(db: Session, document: DBDocument, *, file_path: Path) -> None:
    # Snapshot source identity before rollback can expire mapped attributes.
    document_id, tenant_id, dataset_id = document.id, document.tenant_id, document.dataset_id
    stored_path, metadata = document.file_path, dict(document.doc_metadata or {})
    try:
        db.add(document)
    except Exception:
        with contextlib.suppress(Exception):
            db.rollback()
        await cleanup_unpersisted_source(stored_path, document_metadata=metadata)
        unlink_source(file_path)
        raise
    try:
        db.commit()
    except IntegrityError as exc:
        with contextlib.suppress(Exception):
            db.rollback()
        duplicate = None
        try:
            file_sha256 = get_content_sha256(metadata)
            pipeline_hash = str(metadata.get("pipeline_hash") or "").strip()
            if is_document_dedup_integrity_error(exc) and file_sha256 and pipeline_hash:
                duplicate = find_duplicate_document(
                    db, tenant_id=tenant_id, dataset_id=dataset_id, file_sha256=file_sha256, pipeline_hash=pipeline_hash
                )
        finally:
            await cleanup_unpersisted_source(stored_path, document_metadata=metadata)
            unlink_source(file_path)
        if duplicate is not None:
            raise DuplicatePersistedDocumentError(duplicate) from exc
        raise
    except Exception:
        with contextlib.suppress(Exception):
            db.rollback()
        await cleanup_commit_ambiguous_source(
            document_id=document_id, stored_path=stored_path, file_path=file_path, document_metadata=metadata
        )
        raise
    try:
        db.refresh(document)
    except Exception as exc:
        logger.warning("Document committed but refresh failed: %s", str(exc)[:200])

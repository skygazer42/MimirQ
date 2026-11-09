"""Tenant-scoped document deduplication lookups."""

from collections.abc import Callable
from typing import Any
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Query, Session

from app.models.document import Document as DBDocument
from app.services.document_identity import build_document_dedup_key, get_content_sha256

DUPLICATE_DOCUMENT_PROCESSING_DETAIL = "Duplicate document is currently processing"
DOCUMENT_DEDUP_CONSTRAINT_NAME = "uq_documents_tenant_dataset_dedup_key_active"


class DuplicatePersistedDocumentError(RuntimeError):
    def __init__(self, document: Any) -> None:
        super().__init__("duplicate persisted document")
        self.document = document


def document_matches_dedup_identity(document: Any, *, content_sha256: str, pipeline_hash: str) -> bool:
    expected = build_document_dedup_key(content_sha256=content_sha256, pipeline_hash=pipeline_hash)
    dedup_key = document.dedup_key
    if dedup_key is not None:
        dedup_key = dedup_key.strip()
    if expected and dedup_key == expected:
        return True
    metadata = dict(getattr(document, "doc_metadata", None) or {})
    stored_pipeline_hash = metadata.get("pipeline_hash")
    if stored_pipeline_hash is not None:
        stored_pipeline_hash = stored_pipeline_hash.strip()
    return bool(
        expected
        and get_content_sha256(metadata) == content_sha256.strip().lower()
        and stored_pipeline_hash == pipeline_hash.strip()
    )


def is_document_dedup_integrity_error(exc: IntegrityError) -> bool:
    diag = getattr(exc.orig, "diag", None)
    constraint_name = getattr(diag, "constraint_name", None)
    if constraint_name is not None and constraint_name.strip() == DOCUMENT_DEDUP_CONSTRAINT_NAME:
        return True
    message = str(exc.orig) if exc.orig is not None else str(exc)
    return DOCUMENT_DEDUP_CONSTRAINT_NAME in message


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


def _scan_duplicate_documents(
    db: Session,
    *,
    tenant_id: UUID,
    dataset_id: UUID,
    max_scan: int,
    predicate: Callable[[dict[str, Any]], bool],
) -> DBDocument | None:
    docs = (
        _duplicate_document_query(db, tenant_id=tenant_id, dataset_id=dataset_id)
        .limit(max(1, int(max_scan or 5000)))
        .all()
    )
    for doc in docs or []:
        meta = dict(getattr(doc, "doc_metadata", None) or {})
        if predicate(meta):
            return doc
    return None


def _find_duplicate_document(
    db: Session,
    *,
    tenant_id: UUID,
    dataset_id: UUID | None,
    file_sha256: str,
    pipeline_hash: str,
    max_scan: int = 5000,
) -> DBDocument | None:
    if dataset_id is None:
        return None
    sha = file_sha256.strip().lower()
    ph = pipeline_hash.strip()
    if not sha or not ph:
        return None

    try:
        return (
            _duplicate_document_query(db, tenant_id=tenant_id, dataset_id=dataset_id)
            .filter(
                (DBDocument.doc_metadata["content_sha256"].astext == sha)  # type: ignore[attr-defined]
                | (DBDocument.doc_metadata["file_sha256"].astext == sha)  # type: ignore[attr-defined]
            )
            .filter(DBDocument.doc_metadata["pipeline_hash"].astext == ph)  # type: ignore[attr-defined]
            .first()
        )
    except Exception:
        return _scan_duplicate_documents(
            db,
            tenant_id=tenant_id,
            dataset_id=dataset_id,
            max_scan=max_scan,
            predicate=lambda meta: (
                get_content_sha256(meta) == sha
                and meta.get("pipeline_hash") is not None
                and meta["pipeline_hash"].strip() == ph
            ),
        )


def _find_duplicate_document_by_sha(
    db: Session,
    *,
    tenant_id: UUID,
    dataset_id: UUID | None,
    file_sha256: str,
    max_scan: int = 5000,
) -> DBDocument | None:
    if dataset_id is None:
        return None
    sha = file_sha256.strip().lower()
    if not sha:
        return None

    try:
        return (
            _duplicate_document_query(db, tenant_id=tenant_id, dataset_id=dataset_id)
            .filter(
                (DBDocument.doc_metadata["content_sha256"].astext == sha)  # type: ignore[attr-defined]
                | (DBDocument.doc_metadata["file_sha256"].astext == sha)  # type: ignore[attr-defined]
            )
            .first()
        )
    except Exception:
        return _scan_duplicate_documents(
            db,
            tenant_id=tenant_id,
            dataset_id=dataset_id,
            max_scan=max_scan,
            predicate=lambda meta: get_content_sha256(meta) == sha,
        )


def _find_duplicate_document_for_persist_conflict(
    db: Session,
    *,
    db_document: DBDocument,
) -> DBDocument | None:
    dataset_id = db_document.dataset_id
    if dataset_id is None:
        return None
    doc_metadata = dict(db_document.doc_metadata or {})
    file_sha256 = get_content_sha256(doc_metadata)
    pipeline_hash = doc_metadata.get("pipeline_hash")
    if pipeline_hash is not None:
        pipeline_hash = pipeline_hash.strip()
    if not file_sha256 or not pipeline_hash:
        return None
    return _find_duplicate_document(
        db,
        tenant_id=db_document.tenant_id,
        dataset_id=dataset_id,
        file_sha256=file_sha256,
        pipeline_hash=pipeline_hash,
    )

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_account_id, get_tenant_id
from app.api.schemas.documents import (
    DocumentDetail,
    DocumentVersionDiff,
    DocumentVersionDiffQuery,
    DocumentVersionInfo,
    DocumentVersionList,
)
from app.api.utils import DEFAULT_HTTP_EXCEPTION_RESPONSES
from app.core.database import get_db
from app.core.pipeline_versions import get_active_pipeline_hash
from app.models.document import Document, DocumentChunk
from app.rag.core.logging import get_logger
from app.services import dataset_service
from app.services.audit_log_service import audit_log_event
from app.services.document_access_service import (
    assert_document_readable_for_lifecycle,
    assert_document_writable_for_lifecycle,
)
from app.services.document_version_diff_service import content_hash_multiset_diff
from app.services.indexer import Indexer

DOC_NOT_FOUND_DETAIL = "Document not found"
PIPELINE_HASH_TOO_LONG_DETAIL = "pipeline_hash too long"

logger = get_logger(__name__)

router = APIRouter(responses=DEFAULT_HTTP_EXCEPTION_RESPONSES)


def _get_version_document_or_404(*, db: Session, tenant_id: UUID, document_id: UUID) -> Document:
    document = db.query(Document).filter(Document.id == document_id, Document.tenant_id == tenant_id).first()
    if document is None:
        raise HTTPException(status_code=404, detail=DOC_NOT_FOUND_DETAIL)
    return document


def _normalize_pipeline_hash(pipeline_hash: str, *, required_detail: str) -> str:
    pipeline_hash_norm = pipeline_hash.strip()
    if not pipeline_hash_norm:
        raise HTTPException(status_code=400, detail=required_detail)
    if len(pipeline_hash_norm) > 64:
        raise HTTPException(status_code=400, detail=PIPELINE_HASH_TOO_LONG_DETAIL)
    return pipeline_hash_norm


def _commit_document_version_audit(
    db: Session,
    *,
    tenant_id: UUID,
    account_id: str,
    action: str,
    document_id: UUID,
    details: dict[str, object],
) -> None:
    try:
        audit_log_event(
            db,
            tenant_id=tenant_id,
            actor_id=account_id,
            action=action,
            resource_type="document",
            resource_id=str(document_id),
            details=details,
        )
        db.commit()
    except Exception:
        db.rollback()
        logger.warning(
            "Document version mutation committed but audit logging failed: action=%s document_id=%s",
            action,
            document_id,
            exc_info=True,
        )


def _load_version_signatures(
    *,
    db: Session,
    tenant_id: UUID,
    document_id: UUID,
    target_key: str,
) -> list[str]:
    query = db.query(DocumentChunk.id, DocumentChunk.doc_metadata).filter(
        DocumentChunk.tenant_id == tenant_id,
        DocumentChunk.document_id == document_id,
    )
    if db.get_bind().dialect.name == "postgresql":
        query = query.filter(
            DocumentChunk.doc_metadata["doc_pipeline_key"].astext == target_key,  # type: ignore[attr-defined]
        )
    rows = query.execution_options(stream_results=True).enable_eagerloads(False).all()

    out: list[str] = []
    for chunk_id, meta in rows:
        metadata = meta if isinstance(meta, dict) else {}
        if metadata.get("doc_pipeline_key") != target_key:
            continue
        content_hash = metadata.get("content_hash")
        if content_hash is not None:
            content_hash = content_hash.strip()
        out.append(content_hash or f"id:{chunk_id}")
    return out


def _version_provenance_pair(
    document: Document, *, from_hash: str, to_hash: str
) -> tuple[dict[str, object] | None, dict[str, object] | None]:
    doc_meta = dict(document.doc_metadata or {})
    prov_versions = doc_meta.get("pipeline_provenance_versions")
    if not isinstance(prov_versions, dict):
        return None, None
    from_prov = prov_versions.get(from_hash)
    to_prov = prov_versions.get(to_hash)
    return (from_prov if isinstance(from_prov, dict) else None), (to_prov if isinstance(to_prov, dict) else None)


def _changed_transform_keys(*, from_prov: dict[str, object] | None, to_prov: dict[str, object] | None) -> list[str]:
    if from_prov is None or to_prov is None:
        return []
    from_transforms = from_prov.get("transforms")
    if not isinstance(from_transforms, dict):
        from_transforms = {}
    to_transforms = to_prov.get("transforms")
    if not isinstance(to_transforms, dict):
        to_transforms = {}
    changed: list[str] = []
    for key in sorted(set(from_transforms) | set(to_transforms)):
        from_transform = from_transforms.get(key)
        to_transform = to_transforms.get(key)
        from_hash = from_transform.get("hash") if isinstance(from_transform, dict) else None
        to_hash = to_transform.get("hash") if isinstance(to_transform, dict) else None
        if from_hash != to_hash:
            changed.append(str(key)[:64])
    return changed


def _load_version_chunk_ids(
    *,
    db: Session,
    tenant_id: UUID,
    document_id: UUID,
    target_key: str,
) -> list[UUID]:
    query = db.query(DocumentChunk.id).filter(
        DocumentChunk.tenant_id == tenant_id,
        DocumentChunk.document_id == document_id,
    )
    if db.get_bind().dialect.name == "postgresql":
        rows = query.filter(
            DocumentChunk.doc_metadata["doc_pipeline_key"].astext == target_key,  # type: ignore[attr-defined]
        ).all()
        return [chunk_id for (chunk_id,) in rows]
    rows = query.add_columns(DocumentChunk.doc_metadata).all()
    return [
        chunk_id
        for chunk_id, chunk_meta in rows
        if (chunk_meta if isinstance(chunk_meta, dict) else {}).get("doc_pipeline_key") == target_key
    ]


@router.get("/{document_id}/versions", response_model=DocumentVersionList)
def list_document_versions(
    document_id: UUID,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> DocumentVersionList:
    """
    List document pipeline versions (keyed by pipeline_hash).

    Notes:
    - Versions are inferred from persisted chunks (doc_metadata.doc_pipeline_key).
    - This is best-effort and primarily intended for ops/debug/rollback.
    """
    dataset_service.ensure_member(db, tenant_id, account_id)

    document = _get_version_document_or_404(db=db, tenant_id=tenant_id, document_id=document_id)

    assert_document_readable_for_lifecycle(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        document=document,
    )

    doc_meta = dict(document.doc_metadata or {})
    active_hash = get_active_pipeline_hash(doc_meta)
    active_key = f"{document_id}:{active_hash}" if active_hash else None

    chunks = db.query(DocumentChunk).filter(
        DocumentChunk.tenant_id == tenant_id,
        DocumentChunk.document_id == document_id,
    )
    items: list[DocumentVersionInfo] = []
    if db.get_bind().dialect.name == "postgresql":
        rows = (
            chunks.with_entities(
                DocumentChunk.doc_metadata["pipeline_hash"].astext,  # type: ignore[attr-defined]
                DocumentChunk.doc_metadata["doc_pipeline_key"].astext,  # type: ignore[attr-defined]
                func.count(DocumentChunk.id),
                func.min(DocumentChunk.created_at),
                func.max(DocumentChunk.created_at),
            )
            .group_by(
                DocumentChunk.doc_metadata["pipeline_hash"].astext,  # type: ignore[attr-defined]
                DocumentChunk.doc_metadata["doc_pipeline_key"].astext,  # type: ignore[attr-defined]
            )
            .all()
        )
        for pipeline_hash, doc_pipeline_key, cnt, first_at, last_at in rows:
            pipeline_hash_norm = pipeline_hash.strip() if pipeline_hash is not None else None
            if not pipeline_hash_norm:
                continue
            key = doc_pipeline_key.strip() if doc_pipeline_key is not None else None
            if not key:
                key = f"{document_id}:{pipeline_hash_norm}"
            items.append(
                DocumentVersionInfo(
                    pipeline_hash=pipeline_hash_norm,
                    doc_pipeline_key=key,
                    chunk_count=cnt,
                    first_chunk_at=first_at,
                    last_chunk_at=last_at,
                    active=key == active_key,
                )
            )
    else:
        rows = chunks.with_entities(DocumentChunk.doc_metadata, DocumentChunk.created_at).all()
        by_key: dict[str, DocumentVersionInfo] = {}
        for meta, created_at in rows:
            metadata = meta if isinstance(meta, dict) else {}
            pipeline_hash_norm = metadata.get("pipeline_hash")
            if pipeline_hash_norm is not None:
                pipeline_hash_norm = pipeline_hash_norm.strip()
            if not pipeline_hash_norm:
                continue
            key = metadata.get("doc_pipeline_key")
            if key is not None:
                key = key.strip()
            if not key:
                key = f"{document_id}:{pipeline_hash_norm}"
            if key not in by_key:
                by_key[key] = DocumentVersionInfo(
                    pipeline_hash=pipeline_hash_norm,
                    doc_pipeline_key=key,
                    active=key == active_key,
                )
            entry = by_key[key]
            entry.chunk_count += 1
            if created_at is not None:
                if entry.first_chunk_at is None or created_at < entry.first_chunk_at:
                    entry.first_chunk_at = created_at
                if entry.last_chunk_at is None or created_at > entry.last_chunk_at:
                    entry.last_chunk_at = created_at
        items = list(by_key.values())

    items.sort(
        key=lambda item: (
            item.active,
            item.last_chunk_at is not None,
            item.last_chunk_at,
        ),
        reverse=True,
    )

    return DocumentVersionList(
        document_id=document_id,
        active_pipeline_hash=active_hash,
        pipeline_hash=doc_meta.get("pipeline_hash"),
        items=items,
    )


@router.get("/{document_id}/versions/diff", response_model=DocumentVersionDiff)
def diff_document_versions(
    document_id: UUID,
    params: Annotated[DocumentVersionDiffQuery, Query()],
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> DocumentVersionDiff:
    """
    Diff two document pipeline versions by chunk `content_hash` (multiset semantics).

    Notes:
    - This endpoint never returns chunk text; it is safe for ops/UI debugging.
    - For legacy chunks without `content_hash`, we fall back to chunk id as a unique signature
      (so counts remain accurate, but "unchanged" may be underestimated).
    """
    dataset_service.ensure_member(db, tenant_id, account_id)
    document = _get_version_document_or_404(db=db, tenant_id=tenant_id, document_id=document_id)
    assert_document_readable_for_lifecycle(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        document=document,
    )

    from_hash = _normalize_pipeline_hash(
        params.from_pipeline_hash, required_detail="from/to pipeline_hash are required"
    )
    to_hash = _normalize_pipeline_hash(params.to_pipeline_hash, required_detail="from/to pipeline_hash are required")
    from_sigs = _load_version_signatures(
        db=db,
        tenant_id=tenant_id,
        document_id=document_id,
        target_key=f"{document_id}:{from_hash}",
    )
    if not from_sigs:
        raise HTTPException(status_code=404, detail="from pipeline version not found (no chunks)")
    to_sigs = _load_version_signatures(
        db=db,
        tenant_id=tenant_id,
        document_id=document_id,
        target_key=f"{document_id}:{to_hash}",
    )
    if not to_sigs:
        raise HTTPException(status_code=404, detail="to pipeline version not found (no chunks)")

    diff = content_hash_multiset_diff(
        from_hashes=from_sigs,
        to_hashes=to_sigs,
        sample_limit=params.sample_limit,
    )
    from_prov, to_prov = _version_provenance_pair(document, from_hash=from_hash, to_hash=to_hash)
    return DocumentVersionDiff(
        document_id=document_id,
        from_pipeline_hash=from_hash,
        to_pipeline_hash=to_hash,
        from_chunk_count=diff.from_chunk_count,
        to_chunk_count=diff.to_chunk_count,
        unchanged_chunks=diff.unchanged_chunks,
        added_chunks=diff.added_chunks,
        removed_chunks=diff.removed_chunks,
        added_hashes=list(diff.added_hashes),
        removed_hashes=list(diff.removed_hashes),
        from_provenance=from_prov,
        to_provenance=to_prov,
        changed_transforms=_changed_transform_keys(from_prov=from_prov, to_prov=to_prov),
    )


@router.post(
    "/{document_id}/versions/{pipeline_hash}/activate",
    response_model=DocumentDetail,
)
def activate_document_version(
    document_id: UUID,
    pipeline_hash: str,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> Document:
    """
    Activate (rollback to) a specific pipeline_hash version for retrieval/citations.

    This does not re-run parsing/indexing; it only switches the active version *if* chunks exist.
    """
    dataset_service.ensure_member(db, tenant_id, account_id)

    document = _get_version_document_or_404(db=db, tenant_id=tenant_id, document_id=document_id)

    assert_document_writable_for_lifecycle(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        document=document,
    )

    pipeline_hash_norm = _normalize_pipeline_hash(pipeline_hash, required_detail="pipeline_hash is required")

    target_key = f"{document_id}:{pipeline_hash_norm}"
    chunks = db.query(DocumentChunk).filter(
        DocumentChunk.tenant_id == tenant_id,
        DocumentChunk.document_id == document_id,
        DocumentChunk.doc_metadata["doc_pipeline_key"].astext == target_key,  # type: ignore[attr-defined]
    )
    exists = chunks.with_entities(DocumentChunk.id).limit(1).first()
    if not exists:
        raise HTTPException(status_code=404, detail="Document version not found (no chunks for this pipeline_hash)")

    chunk_count = chunks.with_entities(func.count(DocumentChunk.id)).scalar()
    total_chars = 0
    rows = chunks.with_entities(DocumentChunk.doc_metadata).all()
    for (meta,) in rows:
        metadata = meta if isinstance(meta, dict) else {}
        content_len = metadata.get("content_len")
        if content_len is not None:
            total_chars += int(content_len)

    meta = dict(document.doc_metadata or {})
    meta["active_pipeline_hash"] = pipeline_hash_norm
    meta["active_pipeline_ready"] = True
    document.doc_metadata = meta
    document.chunk_count = chunk_count
    document.total_characters = total_chars
    document.status = "completed"
    document.processing_progress = 100
    document.current_stage = "completed"
    document.error_message = None
    db.commit()
    db.refresh(document)

    _commit_document_version_audit(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        action="document.version.activate",
        document_id=document_id,
        details={
            "pipeline_hash": pipeline_hash_norm,
        },
    )
    return document


@router.delete("/{document_id}/versions/{pipeline_hash}", status_code=204)
def delete_document_version(
    document_id: UUID,
    pipeline_hash: str,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    """
    Delete a non-active document pipeline version.

    Notes:
    - This deletes DB chunks and KG state for the requested pipeline_hash.
    - Vector/BM25 index cleanup is best-effort and logs failures for later repair.
    - Database cleanup failures propagate instead of returning a successful 204.
    - The currently-active version cannot be deleted (use activate to switch first).
    - This endpoint is intended for ops/debug cleanup; it does not re-run processing.
    """
    dataset_service.ensure_member(db, tenant_id, account_id)
    document = _get_version_document_or_404(db=db, tenant_id=tenant_id, document_id=document_id)
    assert_document_writable_for_lifecycle(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        document=document,
    )
    pipeline_hash_norm = _normalize_pipeline_hash(pipeline_hash, required_detail="pipeline_hash is required")
    doc_status = document.status.lower()
    meta = dict(document.doc_metadata or {})
    current_hash = meta.get("pipeline_hash")
    if current_hash is not None:
        current_hash = current_hash.strip()
    if doc_status in {"pending", "processing"} and current_hash == pipeline_hash_norm:
        raise HTTPException(status_code=409, detail="Cannot delete the current in-progress pipeline version")

    active_hash = get_active_pipeline_hash(meta)
    if pipeline_hash_norm == active_hash:
        raise HTTPException(
            status_code=409, detail="Cannot delete the active pipeline version (activate another first)"
        )

    target_key = f"{document_id}:{pipeline_hash_norm}"
    chunk_ids = _load_version_chunk_ids(
        db=db,
        tenant_id=tenant_id,
        document_id=document_id,
        target_key=target_key,
    )
    if not chunk_ids:
        raise HTTPException(status_code=404, detail="Document version not found (no chunks for this pipeline_hash)")

    try:
        Indexer(db).delete_document_chunk_vectors(
            document_id=document_id,
            tenant_id=tenant_id,
            metadata_filter={"doc_pipeline_key": {"$eq": target_key}},
        )
    except Exception:
        logger.warning(
            "Document version vector cleanup failed: document_id=%s pipeline_hash=%s",
            document_id,
            pipeline_hash_norm,
            exc_info=True,
        )
    try:
        from app.rag.retriever import hybrid_retriever

        hybrid_retriever.remove_from_bm25_index_by_metadata_filter(
            tenant_id=tenant_id,
            metadata_filter={"doc_pipeline_key": {"$eq": target_key}},
        )
    except Exception:
        logger.warning(
            "Document version BM25 cleanup failed: document_id=%s pipeline_hash=%s",
            document_id,
            pipeline_hash_norm,
            exc_info=True,
        )

    db.query(DocumentChunk).filter(
        DocumentChunk.tenant_id == tenant_id,
        DocumentChunk.document_id == document_id,
        DocumentChunk.id.in_(chunk_ids),
    ).delete(synchronize_session=False)

    if current_hash == pipeline_hash_norm:
        if active_hash:
            meta["pipeline_hash"] = active_hash
        else:
            meta.pop("pipeline_hash", None)
        document.doc_metadata = meta

    try:
        from app.rag.kg.models import KgRelation

        db.query(KgRelation).filter(
            KgRelation.tenant_id == tenant_id,
            KgRelation.chunk_id.in_(chunk_ids),
        ).delete(synchronize_session=False)

        Indexer(db).delete_event_indexes_for_chunks(
            tenant_id=tenant_id,
            chunk_ids=chunk_ids,
            commit=False,
            prune_orphan_entities=True,
        )
        db.commit()
    except Exception:
        db.rollback()
        raise

    _commit_document_version_audit(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        action="document.version.delete",
        document_id=document_id,
        details={
            "pipeline_hash": pipeline_hash_norm,
            "deleted_chunk_count": len(chunk_ids),
        },
    )
    return Response(status_code=204)

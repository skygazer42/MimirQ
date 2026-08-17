
import contextlib
import uuid
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.api.schemas.document import DocumentDetail, DocumentVersionDiff, DocumentVersionList
from app.core.database import get_db
from app.models.document import Document as DBDocument
from app.models.document import DocumentChunk
from app.rag.core.logging import get_logger
from app.services.audit_log_service import audit_log_event
from app.services.dataset_service import DatasetService
from app.services.document_access_service import (
    assert_document_readable_for_lifecycle,
    assert_document_writable_for_lifecycle,
)
from app.services.indexer import Indexer

_DEFAULT_HTTP_EXCEPTION_RESPONSES = {
    400: {"description": "Bad Request"},
    403: {"description": "Forbidden"},
    404: {"description": "Not Found"},
    409: {"description": "Conflict"},
    416: {"description": "Range Not Satisfiable"},
}

DOC_NOT_FOUND_DETAIL = "Document not found"
PIPELINE_HASH_TOO_LONG_DETAIL = "pipeline_hash too long"

router = APIRouter(responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)


def _get_version_document_or_404(*, db: Session, tenant_id: UUID, document_id: UUID):
    document = (
        db.query(DBDocument)
        .filter(DBDocument.id == document_id, DBDocument.tenant_id == tenant_id)
        .first()
    )
    if not document:
        raise HTTPException(status_code=404, detail=DOC_NOT_FOUND_DETAIL)
    return document


def _normalize_pipeline_hash(pipeline_hash: str, *, required_detail: str) -> str:
    pipeline_hash_norm = str(pipeline_hash or "").strip()
    if not pipeline_hash_norm:
        raise HTTPException(status_code=400, detail=required_detail)
    if len(pipeline_hash_norm) > 64:
        raise HTTPException(status_code=400, detail=PIPELINE_HASH_TOO_LONG_DETAIL)
    return pipeline_hash_norm


def _load_version_signatures(
    *,
    db: Session,
    tenant_id: UUID,
    document_id: UUID,
    target_key: str,
) -> list[str]:
    try:
        rows = (
            db.query(DocumentChunk.id, DocumentChunk.doc_metadata)
            .filter(
                DocumentChunk.tenant_id == tenant_id,
                DocumentChunk.document_id == document_id,
                DocumentChunk.doc_metadata["doc_pipeline_key"].astext == target_key,  # type: ignore[attr-defined]
            )
            .execution_options(stream_results=True)
            .enable_eagerloads(False)
            .all()
        )
    except Exception:
        rows = (
            db.query(DocumentChunk.id, DocumentChunk.doc_metadata)
            .filter(
                DocumentChunk.tenant_id == tenant_id,
                DocumentChunk.document_id == document_id,
            )
            .execution_options(stream_results=True)
            .enable_eagerloads(False)
            .all()
        )

    out: list[str] = []
    for chunk_id, meta in rows or []:
        metadata = meta if isinstance(meta, dict) else {}
        if str(metadata.get("doc_pipeline_key") or "").strip() != target_key:
            continue
        content_hash = str(metadata.get("content_hash") or "").strip()
        out.append(content_hash or f"id:{chunk_id}")
    return out


def _version_provenance_pair(document, *, from_hash: str, to_hash: str) -> tuple[dict[str, object] | None, dict[str, object] | None]:
    doc_meta = dict(document.doc_metadata or {})
    prov_versions = doc_meta.get("pipeline_provenance_versions") if isinstance(doc_meta.get("pipeline_provenance_versions"), dict) else {}
    from_prov = prov_versions.get(from_hash) if isinstance(prov_versions, dict) else None
    to_prov = prov_versions.get(to_hash) if isinstance(prov_versions, dict) else None
    return (from_prov if isinstance(from_prov, dict) else None), (to_prov if isinstance(to_prov, dict) else None)


def _changed_transform_keys(*, from_prov: dict[str, object] | None, to_prov: dict[str, object] | None) -> list[str]:
    if not isinstance(from_prov, dict) or not isinstance(to_prov, dict):
        return []
    from_transforms = from_prov.get("transforms") if isinstance(from_prov.get("transforms"), dict) else {}
    to_transforms = to_prov.get("transforms") if isinstance(to_prov.get("transforms"), dict) else {}
    changed: list[str] = []
    for key in sorted(set(from_transforms.keys()) | set(to_transforms.keys())):
        from_transform = from_transforms.get(key) if isinstance(from_transforms.get(key), dict) else {}
        to_transform = to_transforms.get(key) if isinstance(to_transforms.get(key), dict) else {}
        if str(from_transform.get("hash") or "").strip() != str(to_transform.get("hash") or "").strip():
            changed.append(str(key)[:64])
    return changed


def _load_version_chunk_ids(
    *,
    db: Session,
    tenant_id: UUID,
    document_id: UUID,
    target_key: str,
) -> list[UUID]:
    try:
        rows = (
            db.query(DocumentChunk.id)
            .filter(
                DocumentChunk.tenant_id == tenant_id,
                DocumentChunk.document_id == document_id,
                DocumentChunk.doc_metadata["doc_pipeline_key"].astext == target_key,  # type: ignore[attr-defined]
            )
            .all()
        )
        return [chunk_id for (chunk_id,) in rows if isinstance(chunk_id, UUID)]
    except Exception:
        rows = (
            db.query(DocumentChunk.id, DocumentChunk.doc_metadata)
            .filter(
                DocumentChunk.tenant_id == tenant_id,
                DocumentChunk.document_id == document_id,
            )
            .all()
        )
        return [
            chunk_id
            for chunk_id, chunk_meta in rows
            if str((chunk_meta if isinstance(chunk_meta, dict) else {}).get("doc_pipeline_key") or "").strip() == target_key
        ]


@router.get("/{document_id}/versions", response_model=DocumentVersionList, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def list_document_versions(
    document_id: uuid.UUID,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    List document pipeline versions (keyed by pipeline_hash).

    Notes:
    - Versions are inferred from persisted chunks (doc_metadata.doc_pipeline_key).
    - This is best-effort and primarily intended for ops/debug/rollback.
    """
    DatasetService.ensure_member(db, tenant_id, account_id)

    document = (
        db.query(DBDocument)
        .filter(DBDocument.id == document_id, DBDocument.tenant_id == tenant_id)
        .first()
    )
    if not document:
        raise HTTPException(status_code=404, detail=DOC_NOT_FOUND_DETAIL)

    assert_document_readable_for_lifecycle(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        document=document,
    )

    from app.core.pipeline_versions import get_active_pipeline_hash

    doc_meta = dict(document.doc_metadata or {})
    active_hash = get_active_pipeline_hash(doc_meta)
    active_key = f"{document_id}:{active_hash}" if active_hash else None

    items = []
    try:
        rows = (
            db.query(
                DocumentChunk.doc_metadata["pipeline_hash"].astext,  # type: ignore[attr-defined]
                DocumentChunk.doc_metadata["doc_pipeline_key"].astext,  # type: ignore[attr-defined]
                func.count(DocumentChunk.id),
                func.min(DocumentChunk.created_at),
                func.max(DocumentChunk.created_at),
            )
            .filter(
                DocumentChunk.tenant_id == tenant_id,
                DocumentChunk.document_id == document_id,
            )
            .group_by(
                DocumentChunk.doc_metadata["pipeline_hash"].astext,  # type: ignore[attr-defined]
                DocumentChunk.doc_metadata["doc_pipeline_key"].astext,  # type: ignore[attr-defined]
            )
            .all()
        )
        for pipeline_hash, doc_pipeline_key, cnt, first_at, last_at in rows:
            pipeline_hash_norm = str(pipeline_hash or "").strip()
            key = str(doc_pipeline_key or "").strip() or (
                f"{document_id}:{pipeline_hash_norm}" if pipeline_hash_norm else str(document_id)
            )
            if not pipeline_hash_norm:
                continue
            items.append(
                {
                    "pipeline_hash": pipeline_hash_norm,
                    "doc_pipeline_key": key,
                    "chunk_count": int(cnt or 0),
                    "first_chunk_at": first_at,
                    "last_chunk_at": last_at,
                    "active": bool(active_key and key == active_key),
                }
            )
    except Exception:
        rows = (
            db.query(DocumentChunk.doc_metadata, DocumentChunk.created_at)
            .filter(DocumentChunk.tenant_id == tenant_id, DocumentChunk.document_id == document_id)
            .all()
        )
        by_key: dict[str, dict] = {}
        for meta, created_at in rows:
            metadata = meta if isinstance(meta, dict) else {}
            pipeline_hash_norm = str(metadata.get("pipeline_hash") or "").strip()
            if not pipeline_hash_norm:
                continue
            key = str(metadata.get("doc_pipeline_key") or "").strip() or f"{document_id}:{pipeline_hash_norm}"
            entry = by_key.get(key) or {
                "pipeline_hash": pipeline_hash_norm,
                "doc_pipeline_key": key,
                "chunk_count": 0,
                "first_chunk_at": None,
                "last_chunk_at": None,
                "active": bool(active_key and key == active_key),
            }
            entry["chunk_count"] = int(entry.get("chunk_count") or 0) + 1
            if created_at:
                if entry["first_chunk_at"] is None or created_at < entry["first_chunk_at"]:
                    entry["first_chunk_at"] = created_at
                if entry["last_chunk_at"] is None or created_at > entry["last_chunk_at"]:
                    entry["last_chunk_at"] = created_at
            by_key[key] = entry
        items = list(by_key.values())

    items.sort(
        key=lambda item: (
            item.get("active") is True,
            item.get("last_chunk_at") is not None,
            item.get("last_chunk_at"),
        ),
        reverse=True,
    )

    return {
        "document_id": document_id,
        "active_pipeline_hash": active_hash,
        "pipeline_hash": str(doc_meta.get("pipeline_hash") or "").strip() or None,
        "items": items,
    }


@router.get("/{document_id}/versions/diff", response_model=DocumentVersionDiff, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def diff_document_versions(
    document_id: uuid.UUID,
    from_pipeline_hash: Annotated[
        str,
        Query(..., alias="from", max_length=64, description="Source pipeline_hash version (from)"),
    ],
    to_pipeline_hash: Annotated[
        str,
        Query(..., alias="to", max_length=64, description="Target pipeline_hash version (to)"),
    ],
    sample_limit: Annotated[
        int,
        Query(ge=0, le=200, description="Max hash samples included in added_hashes/removed_hashes"),
    ] = 50,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Diff two document pipeline versions by chunk `content_hash` (multiset semantics).

    Notes:
    - This endpoint never returns chunk text; it is safe for ops/UI debugging.
    - For legacy chunks without `content_hash`, we fall back to chunk id as a unique signature
      (so counts remain accurate, but "unchanged" may be underestimated).
    """
    DatasetService.ensure_member(db, tenant_id, account_id)
    document = _get_version_document_or_404(db=db, tenant_id=tenant_id, document_id=document_id)
    assert_document_readable_for_lifecycle(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        document=document,
    )

    from_hash = _normalize_pipeline_hash(from_pipeline_hash, required_detail="from/to pipeline_hash are required")
    to_hash = _normalize_pipeline_hash(to_pipeline_hash, required_detail="from/to pipeline_hash are required")
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

    from app.services.document_version_diff_service import content_hash_multiset_diff

    diff = content_hash_multiset_diff(
        from_hashes=from_sigs,
        to_hashes=to_sigs,
        sample_limit=int(sample_limit or 0),
    )
    from_prov, to_prov = _version_provenance_pair(document, from_hash=from_hash, to_hash=to_hash)
    return {
        "document_id": document_id,
        "from_pipeline_hash": from_hash,
        "to_pipeline_hash": to_hash,
        "from_chunk_count": int(diff.from_chunk_count),
        "to_chunk_count": int(diff.to_chunk_count),
        "unchanged_chunks": int(diff.unchanged_chunks),
        "added_chunks": int(diff.added_chunks),
        "removed_chunks": int(diff.removed_chunks),
        "added_hashes": list(diff.added_hashes),
        "removed_hashes": list(diff.removed_hashes),
        "from_provenance": from_prov,
        "to_provenance": to_prov,
        "changed_transforms": _changed_transform_keys(from_prov=from_prov, to_prov=to_prov),
    }


@router.post(
    "/{document_id}/versions/{pipeline_hash}/activate",
    response_model=DocumentDetail,
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
def activate_document_version(
    document_id: uuid.UUID,
    pipeline_hash: str,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Activate (rollback to) a specific pipeline_hash version for retrieval/citations.

    This does not re-run parsing/indexing; it only switches the active version *if* chunks exist.
    """
    DatasetService.ensure_member(db, tenant_id, account_id)

    document = (
        db.query(DBDocument)
        .filter(DBDocument.id == document_id, DBDocument.tenant_id == tenant_id)
        .first()
    )
    if not document:
        raise HTTPException(status_code=404, detail=DOC_NOT_FOUND_DETAIL)

    assert_document_writable_for_lifecycle(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        document=document,
    )

    pipeline_hash_norm = str(pipeline_hash or "").strip()
    if not pipeline_hash_norm:
        raise HTTPException(status_code=400, detail="pipeline_hash is required")
    if len(pipeline_hash_norm) > 64:
        raise HTTPException(status_code=400, detail=PIPELINE_HASH_TOO_LONG_DETAIL)

    target_key = f"{document_id}:{pipeline_hash_norm}"
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
    if not exists:
        raise HTTPException(status_code=404, detail="Document version not found (no chunks for this pipeline_hash)")

    chunk_count = int(
        db.query(func.count(DocumentChunk.id))
        .filter(
            DocumentChunk.tenant_id == tenant_id,
            DocumentChunk.document_id == document_id,
            DocumentChunk.doc_metadata["doc_pipeline_key"].astext == target_key,  # type: ignore[attr-defined]
        )
        .scalar()
        or 0
    )
    total_chars = 0
    try:
        rows = (
            db.query(DocumentChunk.doc_metadata)
            .filter(
                DocumentChunk.tenant_id == tenant_id,
                DocumentChunk.document_id == document_id,
                DocumentChunk.doc_metadata["doc_pipeline_key"].astext == target_key,  # type: ignore[attr-defined]
            )
            .all()
        )
        for (meta,) in rows:
            metadata = meta if isinstance(meta, dict) else {}
            try:
                total_chars += int(metadata.get("content_len") or 0)
            except Exception:
                get_logger(__name__).debug("Skipping item after non-critical exception", exc_info=True)
                continue
    except Exception:
        total_chars = 0

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

    audit_log_event(
        db,
        tenant_id=tenant_id,
        actor_id=account_id,
        action="document.version.activate",
        resource_type="document",
        resource_id=str(document_id),
        details={
            "pipeline_hash": pipeline_hash_norm,
        },
    )
    try:
        db.commit()
    except Exception:
        db.rollback()
    return document


@router.delete("/{document_id}/versions/{pipeline_hash}", status_code=204, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def delete_document_version(
    document_id: uuid.UUID,
    pipeline_hash: str,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Delete a non-active document pipeline version (best-effort cleanup).

    Notes:
    - This deletes DB chunks for the requested pipeline_hash and best-effort removes
      vectors/BM25 index entries for that version.
    - The currently-active version cannot be deleted (use activate to switch first).
    - This endpoint is intended for ops/debug cleanup; it does not re-run processing.
    """
    DatasetService.ensure_member(db, tenant_id, account_id)
    document = _get_version_document_or_404(db=db, tenant_id=tenant_id, document_id=document_id)
    assert_document_writable_for_lifecycle(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        document=document,
    )
    pipeline_hash_norm = _normalize_pipeline_hash(pipeline_hash, required_detail="pipeline_hash is required")
    doc_status = str(getattr(document, "status", "") or "").lower()
    meta = dict(getattr(document, "doc_metadata", None) or {})
    current_hash = str(meta.get("pipeline_hash") or "").strip()
    if doc_status in {"pending", "processing"} and current_hash == pipeline_hash_norm:
        raise HTTPException(status_code=409, detail="Cannot delete the current in-progress pipeline version")

    active_hash = str(meta.get("active_pipeline_hash") or meta.get("pipeline_hash") or "").strip()
    if active_hash and pipeline_hash_norm == active_hash:
        raise HTTPException(status_code=409, detail="Cannot delete the active pipeline version (activate another first)")

    target_key = f"{document_id}:{pipeline_hash_norm}"
    chunk_ids = _load_version_chunk_ids(
        db=db,
        tenant_id=tenant_id,
        document_id=document_id,
        target_key=target_key,
    )
    if not chunk_ids:
        raise HTTPException(status_code=404, detail="Document version not found (no chunks for this pipeline_hash)")

    with contextlib.suppress(Exception):
        Indexer(db).delete_document_chunk_vectors(
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

    db.query(DocumentChunk).filter(
        DocumentChunk.tenant_id == tenant_id,
        DocumentChunk.document_id == document_id,
        DocumentChunk.id.in_(chunk_ids),
    ).delete(synchronize_session=False)

    if current_hash and current_hash == pipeline_hash_norm:
        if active_hash:
            meta["pipeline_hash"] = active_hash
        else:
            meta.pop("pipeline_hash", None)
        document.doc_metadata = meta

    db.commit()

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
        with contextlib.suppress(Exception):
            db.rollback()

    audit_log_event(
        db,
        tenant_id=tenant_id,
        actor_id=account_id,
        action="document.version.delete",
        resource_type="document",
        resource_id=str(document_id),
        details={
            "pipeline_hash": pipeline_hash_norm,
            "deleted_chunk_count": len(chunk_ids),
        },
    )
    try:
        db.commit()
    except Exception:
        db.rollback()
    return Response(status_code=204)

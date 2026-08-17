import contextlib
import uuid
from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import func
from sqlalchemy.orm import Session

import app.api.v1.documents as documents_module
from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.api.schemas.document import (
    DocumentChunkCreateRequest,
    DocumentChunkReembedRequest,
    DocumentChunkReembedResponse,
    DocumentChunkSchema,
    DocumentChunkUpdateRequest,
)
from app.core.database import get_db

router = APIRouter(responses=documents_module._DEFAULT_HTTP_EXCEPTION_RESPONSES)


@router.post(
    "/{document_id}/chunks",
    response_model=DocumentChunkSchema,
    status_code=201,
    responses=documents_module._DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
def create_document_chunk(
    document_id: uuid.UUID,
    payload: DocumentChunkCreateRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Create a new chunk for a document (appends to the active pipeline version).

    This is intended for post-ingest manual chunk editing. It does not re-parse the source file.
    """

    documents_module.DatasetService.ensure_member(db, tenant_id, account_id)

    document = (
        db.query(documents_module.DBDocument)
        .filter(documents_module.DBDocument.id == document_id, documents_module.DBDocument.tenant_id == tenant_id)
        .first()
    )
    if not document:
        raise HTTPException(status_code=404, detail=documents_module.DOC_NOT_FOUND_DETAIL)

    documents_module._assert_document_writable_for_chunk_ops(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        document=document,
    )

    current_status = str(document.status or "").lower()
    if current_status in {"pending", "processing"}:
        raise HTTPException(status_code=409, detail=f"Cannot edit chunks for a {current_status} document")

    doc_meta = dict(getattr(document, "doc_metadata", None) or {})
    active_key = documents_module._resolve_active_doc_pipeline_key(document_id, doc_meta)
    active_hash = str(doc_meta.get("active_pipeline_hash") or doc_meta.get("pipeline_hash") or "").strip()

    query = db.query(func.max(documents_module.DocumentChunk.chunk_index)).filter(
        documents_module.DocumentChunk.tenant_id == tenant_id,
        documents_module.DocumentChunk.document_id == document_id,
    )
    if active_key:
        query = query.filter(
            documents_module.DocumentChunk.doc_metadata["doc_pipeline_key"].astext == active_key  # type: ignore[attr-defined]
        )
    max_idx = query.scalar()
    next_index = int(max_idx or -1) + 1

    chunk_uuid = uuid.uuid4()
    meta = dict(payload.metadata or {})
    meta.setdefault("tenant_id", str(tenant_id))
    meta.setdefault("document_id", str(document_id))
    meta.setdefault("chunk_id", str(chunk_uuid))
    meta.setdefault("chunk_index", int(next_index))
    if active_hash:
        meta.setdefault("pipeline_hash", active_hash[:64])
        meta.setdefault("doc_pipeline_key", active_key)

    vector_id: str | None = None
    indexer = documents_module.Indexer(db)
    try:
        vector_id = indexer.upsert_document_chunk_vector(
            document_id=document_id,
            tenant_id=tenant_id,
            content=payload.content,
            metadata=meta,
        )
    except Exception:
        vector_id = None

    chunk = documents_module.DocumentChunk(
        id=chunk_uuid,
        tenant_id=tenant_id,
        document_id=document_id,
        chunk_index=next_index,
        content=payload.content,
        page_number=payload.page_number,
        start_char=payload.start_char,
        end_char=payload.end_char,
        doc_metadata=meta,
        vector_id=vector_id,
    )
    db.add(chunk)
    document.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(chunk)

    try:
        documents_module.Indexer(db)._update_bm25_for_chunks(
            db_chunks=[chunk],
            tenant_id=tenant_id,
            document_id=document_id,
            default_source=str(getattr(document, "filename", "") or "unknown"),
            enable_bm25=bool(getattr(documents_module.settings, "BM25_INDEX_ENABLED", True)),
        )
    except Exception as exc:  # noqa: BLE001
        documents_module.logger.debug(
            "BM25 upsert failed for chunk %s: %s",
            str(getattr(chunk, "id", "") or "?"),
            str(exc)[:200],
        )

    try:
        stat_q = db.query(
            func.count(documents_module.DocumentChunk.id),
            func.sum(func.length(documents_module.DocumentChunk.content)),
        ).filter(
            documents_module.DocumentChunk.tenant_id == tenant_id,
            documents_module.DocumentChunk.document_id == document_id,
        )
        if active_key:
            stat_q = stat_q.filter(
                documents_module.DocumentChunk.doc_metadata["doc_pipeline_key"].astext == active_key  # type: ignore[attr-defined]
            )
        cnt, total_chars = stat_q.first() or (None, None)
        document.chunk_count = int(cnt or 0)
        document.total_characters = int(total_chars or 0)
        db.commit()
    except Exception:
        db.rollback()

    documents_module.audit_log_event(
        db,
        tenant_id=tenant_id,
        actor_id=account_id,
        action="document.chunk.create",
        resource_type="document",
        resource_id=str(document_id),
        details={"chunk_id": str(chunk.id), "chunk_index": int(chunk.chunk_index)},
    )
    with contextlib.suppress(Exception):
        db.commit()

    return chunk


def _load_chunk_write_document(
    *,
    db: Session,
    tenant_id: UUID,
    account_id: str,
    document_id: UUID,
    edit_verb: str,
):
    documents_module.DatasetService.ensure_member(db, tenant_id, account_id)
    document = documents_module._get_document_for_chunk_ops(db, tenant_id, document_id)
    if not document:
        raise HTTPException(status_code=404, detail=documents_module.DOC_NOT_FOUND_DETAIL)
    documents_module._assert_document_writable_for_chunk_ops(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        document=document,
    )
    current_status = str(getattr(document, "status", "") or "").lower()
    if current_status in {"pending", "processing"}:
        raise HTTPException(status_code=409, detail=f"Cannot {edit_verb} for a {current_status} document")
    doc_meta = dict(getattr(document, "doc_metadata", None) or {})
    active_key = documents_module._resolve_active_doc_pipeline_key(document_id, doc_meta)
    return document, active_key


def _get_active_chunk_or_404(
    *,
    db: Session,
    tenant_id: UUID,
    document_id: UUID,
    chunk_id: UUID,
    active_key: str | None,
):
    chunk = documents_module._get_chunk_for_chunk_ops(db, tenant_id, document_id, chunk_id)
    if not chunk:
        raise HTTPException(status_code=404, detail=documents_module.CHUNK_NOT_FOUND_DETAIL)
    chunk_key = str((getattr(chunk, "doc_metadata", None) or {}).get("doc_pipeline_key") or "").strip()
    if active_key and chunk_key and chunk_key != active_key:
        raise HTTPException(status_code=409, detail=documents_module.CHUNK_NOT_ACTIVE_PIPELINE_DETAIL)
    return chunk


def _apply_chunk_payload_updates(
    *,
    chunk,
    payload: DocumentChunkUpdateRequest,
    tenant_id: UUID,
    document_id: UUID,
    active_key: str | None,
) -> None:
    for field in ("content", "page_number", "start_char", "end_char"):
        value = getattr(payload, field)
        if value is not None:
            setattr(chunk, field, value)
    if payload.metadata is None or not isinstance(payload.metadata, dict):
        return
    meta = documents_module._apply_chunk_metadata_patch(current=dict(chunk.doc_metadata or {}), patch=payload.metadata)
    meta["tenant_id"] = str(tenant_id)
    meta["document_id"] = str(document_id)
    meta["chunk_id"] = str(chunk.id)
    meta["chunk_index"] = int(chunk.chunk_index)
    if active_key:
        meta.setdefault("doc_pipeline_key", active_key)
    chunk.doc_metadata = meta


def _reindex_chunk_after_patch(
    *,
    db: Session,
    document,
    chunk,
    tenant_id: UUID,
    document_id: UUID,
) -> tuple[str, dict[str, Any], str | None, str | None]:
    strictness = documents_module._normalize_index_consistency_strictness(patch_mode=True)
    emit_drift_markers = bool(getattr(documents_module.settings, "INDEX_CONSISTENCY_EMIT_DRIFT_MARKERS", True))
    drift_markers: list[dict[str, Any]] = []
    vector_error: str | None = None
    bm25_error: str | None = None
    vector_id_after: str | None = None
    indexer = documents_module.Indexer(db)

    try:
        indexer.delete_document_chunk_vectors(
            document_id=document_id,
            tenant_id=tenant_id,
            metadata_filter={"chunk_id": {"$eq": str(chunk.id)}},
        )
    except NotImplementedError:
        vector_error = "vector backend does not support chunk-level updates"
    except Exception as exc:
        vector_error = f"vector delete failed: {str(exc)[:160]}"

    try:
        meta_for_vector = dict(chunk.doc_metadata or {})
        vector_id_after = indexer.upsert_document_chunk_vector(
            document_id=document_id,
            tenant_id=tenant_id,
            content=chunk.content,
            metadata=meta_for_vector,
        )
        if vector_id_after:
            chunk.doc_metadata = meta_for_vector
            chunk.vector_id = vector_id_after
            db.commit()
            db.refresh(chunk)
        else:
            vector_error = vector_error or "vector add returned empty id"
    except Exception as exc:
        db.rollback()
        vector_error = vector_error or f"vector add failed: {str(exc)[:160]}"

    try:
        documents_module.Indexer(db)._update_bm25_for_chunks(
            db_chunks=[chunk],
            tenant_id=tenant_id,
            document_id=document_id,
            default_source=str(getattr(document, "filename", "") or "unknown"),
            enable_bm25=bool(getattr(documents_module.settings, "BM25_INDEX_ENABLED", True)),
        )
    except Exception:
        bm25_error = "bm25 upsert failed"

    if emit_drift_markers and vector_error:
        drift_markers.append(
            documents_module.build_index_drift_marker(
                operation=documents_module.CHUNK_PATCH_OPERATION,
                strictness=strictness,
                tenant_id=tenant_id,
                document_id=document_id,
                chunk_id=chunk.id,
                channel="vector",
                reason=vector_error,
            )
        )
    if emit_drift_markers and bm25_error:
        drift_markers.append(
            documents_module.build_index_drift_marker(
                operation=documents_module.CHUNK_PATCH_OPERATION,
                strictness=strictness,
                tenant_id=tenant_id,
                document_id=document_id,
                chunk_id=chunk.id,
                channel="bm25",
                reason=bm25_error,
            )
        )

    operation_result = documents_module._build_chunk_index_operation_result(
        operation=documents_module.CHUNK_PATCH_OPERATION,
        strictness=strictness,
        vector=documents_module._build_index_channel_result(
            status=("error" if vector_error else "ok"),
            attempted=True,
            error=vector_error,
            vector_id=vector_id_after,
        ),
        bm25=documents_module._build_index_channel_result(
            status=("error" if bm25_error else "ok"),
            attempted=True,
            error=bm25_error,
        ),
        kg=None,
        drift_markers=drift_markers,
    )
    documents_module._persist_chunk_index_operation_result(
        db=db,
        chunk=chunk,
        result=operation_result,
        drift_markers=drift_markers,
    )
    return strictness, operation_result, vector_error, bm25_error


async def _delete_chunk_indexes(
    *,
    db: Session,
    document,
    chunk,
    tenant_id: UUID,
    account_id: str,
    document_id: UUID,
) -> tuple[str, str | None, str | None]:
    from app.rag.retriever import hybrid_retriever

    strictness = documents_module._normalize_index_consistency_strictness(patch_mode=False)
    vector_error: str | None = None
    bm25_error: str | None = None
    indexer = documents_module.Indexer(db)
    try:
        indexer.delete_document_chunk_vectors(
            document_id=document_id,
            tenant_id=tenant_id,
            metadata_filter={"chunk_id": {"$eq": str(chunk.id)}},
        )
    except NotImplementedError as exc:
        vector_error = "vector backend does not support chunk-level deletes"
        if strictness != "strict":
            raise HTTPException(status_code=409, detail="Vector backend does not support chunk-level deletes") from exc
    except Exception as exc:
        vector_error = f"vector delete failed: {str(exc)[:160]}"

    try:
        hybrid_retriever.remove_from_bm25_index_by_metadata_filter(
            tenant_id=tenant_id,
            metadata_filter={"chunk_id": {"$eq": str(chunk.id)}},
        )
    except Exception:
        bm25_error = "bm25 delete failed"

    if vector_error or bm25_error:
        await documents_module._record_chunk_index_drift(
            db=db,
            document=document,
            chunk=chunk,
            tenant_id=tenant_id,
            account_id=account_id,
            operation="chunk.delete",
            strictness=strictness,
            vector_error=vector_error,
            bm25_error=bm25_error,
        )
    return strictness, vector_error, bm25_error


def _refresh_document_chunk_stats(
    *, db: Session, tenant_id: UUID, document_id: UUID, document, active_key: str | None
) -> None:
    try:
        stat_q = db.query(
            func.count(documents_module.DocumentChunk.id),
            func.sum(func.length(documents_module.DocumentChunk.content)),
        ).filter(
            documents_module.DocumentChunk.tenant_id == tenant_id,
            documents_module.DocumentChunk.document_id == document_id,
        )
        if active_key:
            stat_q = stat_q.filter(
                documents_module.DocumentChunk.doc_metadata["doc_pipeline_key"].astext == active_key  # type: ignore[attr-defined]
            )
        cnt, total_chars = stat_q.first() or (None, None)
        document.chunk_count = int(cnt or 0)
        document.total_characters = int(total_chars or 0)
        db.commit()
    except Exception:
        db.rollback()


def _cleanup_deleted_chunk_kg(*, db: Session, tenant_id: UUID, chunk_id: UUID) -> None:
    try:
        from app.rag.kg.models import KgRelation

        db.query(KgRelation).filter(
            KgRelation.tenant_id == tenant_id,
            KgRelation.chunk_id == chunk_id,
        ).delete(synchronize_session=False)

        documents_module.Indexer(db).delete_event_indexes_for_chunks(
            tenant_id=tenant_id,
            chunk_ids=[chunk_id],
            commit=False,
            prune_orphan_entities=True,
        )
        db.commit()
    except Exception:
        with contextlib.suppress(Exception):
            db.rollback()


def _reembed_single_chunk(
    *,
    db: Session,
    document,
    chunk,
    tenant_id: UUID,
    document_id: UUID,
    account_id: str,
    indexer,
) -> bool:
    from app.rag.retriever import hybrid_retriever

    meta_for_vector = dict(getattr(chunk, "doc_metadata", None) or {})
    meta_for_vector.setdefault("tenant_id", str(tenant_id))
    meta_for_vector.setdefault("document_id", str(document_id))
    meta_for_vector.setdefault("chunk_id", str(chunk.id))
    meta_for_vector.setdefault("chunk_index", int(getattr(chunk, "chunk_index", 0) or 0))

    try:
        indexer.delete_document_chunk_vectors(
            document_id=document_id,
            tenant_id=tenant_id,
            metadata_filter={"chunk_id": {"$eq": str(chunk.id)}},
        )
    except Exception as exc:  # noqa: BLE001
        documents_module.logger.debug("Vector filtered delete failed for chunk %s: %s", str(chunk.id), str(exc)[:160])

    try:
        vector_id = indexer.upsert_document_chunk_vector(
            document_id=document_id,
            tenant_id=tenant_id,
            content=chunk.content,
            metadata=meta_for_vector,
        )
        if vector_id:
            chunk.doc_metadata = meta_for_vector
            chunk.vector_id = vector_id
    except Exception:
        return False

    try:
        bm25_meta = dict(meta_for_vector)
        bm25_meta.setdefault("source", bm25_meta.get("source", str(getattr(document, "filename", "") or "unknown")))
        bm25_doc = documents_module.Document(
            page_content=str(getattr(chunk, "content", "") or ""),
            id=str(chunk.id),
            metadata=bm25_meta,
        )
        hybrid_retriever.upsert_bm25_documents([bm25_doc], tenant_id=tenant_id, db=db)
    except Exception as exc:  # noqa: BLE001
        documents_module.logger.debug("BM25 upsert failed for chunk %s: %s", str(chunk.id), str(exc)[:160])

    documents_module.audit_log_event(
        db,
        tenant_id=tenant_id,
        actor_id=account_id,
        action="document.chunk.reembed",
        resource_type="document",
        resource_id=str(document_id),
        details={"chunk_id": str(chunk.id), "chunk_index": int(getattr(chunk, "chunk_index", 0) or 0)},
    )
    return True


@router.patch(
    "/{document_id}/chunks/{chunk_id}",
    response_model=DocumentChunkSchema,
    responses=documents_module._DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
def patch_document_chunk(
    document_id: uuid.UUID,
    chunk_id: uuid.UUID,
    payload: DocumentChunkUpdateRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Patch a chunk and update its indexes (vector + BM25) best-effort.
    """
    document, active_key = _load_chunk_write_document(
        db=db,
        tenant_id=tenant_id,
        account_id=account_id,
        document_id=document_id,
        edit_verb="edit chunks",
    )
    chunk = _get_active_chunk_or_404(
        db=db,
        tenant_id=tenant_id,
        document_id=document_id,
        chunk_id=chunk_id,
        active_key=active_key,
    )
    _apply_chunk_payload_updates(
        chunk=chunk,
        payload=payload,
        tenant_id=tenant_id,
        document_id=document_id,
        active_key=active_key,
    )
    document.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(chunk)
    strictness, operation_result, vector_error, bm25_error = _reindex_chunk_after_patch(
        db=db,
        document=document,
        chunk=chunk,
        tenant_id=tenant_id,
        document_id=document_id,
    )

    documents_module.audit_log_event(
        db,
        tenant_id=tenant_id,
        actor_id=account_id,
        action="document.chunk.update",
        resource_type="document",
        resource_id=str(document_id),
        details={
            "chunk_id": str(chunk.id),
            "chunk_index": int(chunk.chunk_index),
            "index_operation_success": bool(operation_result.get("success")),
            "index_consistency_strictness": strictness,
        },
    )
    with contextlib.suppress(Exception):
        db.commit()

    if strictness == "strict" and (vector_error or bm25_error):
        raise HTTPException(status_code=409, detail="Index consistency strict mode blocked patch; drift marker emitted")

    return chunk


@router.delete(
    "/{document_id}/chunks/{chunk_id}",
    status_code=204,
    responses=documents_module._DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
async def delete_document_chunk(
    document_id: uuid.UUID,
    chunk_id: uuid.UUID,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Delete a chunk and update its indexes (vector + BM25) best-effort.
    """
    document, active_key = _load_chunk_write_document(
        db=db,
        tenant_id=tenant_id,
        account_id=account_id,
        document_id=document_id,
        edit_verb="edit chunks",
    )
    chunk = _get_active_chunk_or_404(
        db=db,
        tenant_id=tenant_id,
        document_id=document_id,
        chunk_id=chunk_id,
        active_key=active_key,
    )
    strictness, vector_error, bm25_error = await _delete_chunk_indexes(
        db=db,
        document=document,
        chunk=chunk,
        tenant_id=tenant_id,
        account_id=account_id,
        document_id=document_id,
    )
    if strictness == "strict" and (vector_error or bm25_error):
        raise HTTPException(status_code=409, detail="Index consistency strict mode blocked delete; drift item recorded")
    db.delete(chunk)
    document.updated_at = datetime.now(UTC)
    db.commit()
    _refresh_document_chunk_stats(
        db=db,
        tenant_id=tenant_id,
        document_id=document_id,
        document=document,
        active_key=active_key,
    )
    _cleanup_deleted_chunk_kg(db=db, tenant_id=tenant_id, chunk_id=chunk_id)
    documents_module.audit_log_event(
        db,
        tenant_id=tenant_id,
        actor_id=account_id,
        action="document.chunk.delete",
        resource_type="document",
        resource_id=str(document_id),
        details={
            "chunk_id": str(chunk_id),
            "index_operation_success": not bool(vector_error or bm25_error),
            "index_consistency_strictness": strictness,
        },
    )
    with contextlib.suppress(Exception):
        db.commit()

    return Response(status_code=204)


@router.post(
    "/{document_id}/chunks/{chunk_id}/disable",
    response_model=DocumentChunkSchema,
    responses=documents_module._DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
async def disable_document_chunk(
    document_id: uuid.UUID,
    chunk_id: uuid.UUID,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """Disable a chunk (exclude it from retrieval/indexing)."""
    from app.rag.retriever import hybrid_retriever

    documents_module.DatasetService.ensure_member(db, tenant_id, account_id)

    document = documents_module._get_document_for_chunk_ops(db, tenant_id, document_id)
    if not document:
        raise HTTPException(status_code=404, detail=documents_module.DOC_NOT_FOUND_DETAIL)
    documents_module._assert_document_writable_for_chunk_ops(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        document=document,
    )

    current_status = str(getattr(document, "status", "") or "").lower()
    if current_status in {"pending", "processing"}:
        raise HTTPException(status_code=409, detail=f"Cannot edit chunks for a {current_status} document")

    chunk = documents_module._get_chunk_for_chunk_ops(db, tenant_id, document_id, chunk_id)
    if not chunk:
        raise HTTPException(status_code=404, detail=documents_module.CHUNK_NOT_FOUND_DETAIL)

    doc_meta = dict(getattr(document, "doc_metadata", None) or {})
    active_key = documents_module._resolve_active_doc_pipeline_key(document_id, doc_meta)
    chunk_key = str((getattr(chunk, "doc_metadata", None) or {}).get("doc_pipeline_key") or "").strip()
    if active_key and chunk_key and chunk_key != active_key:
        raise HTTPException(status_code=409, detail=documents_module.CHUNK_NOT_ACTIVE_PIPELINE_DETAIL)

    strictness = documents_module._normalize_index_consistency_strictness(patch_mode=False)
    vector_error: str | None = None
    bm25_error: str | None = None

    indexer = documents_module.Indexer(db)
    try:
        indexer.delete_document_chunk_vectors(
            document_id=document_id,
            tenant_id=tenant_id,
            metadata_filter={"chunk_id": {"$eq": str(chunk.id)}},
        )
    except Exception as exc:
        vector_error = f"vector delete failed: {str(exc)[:160]}"

    try:
        hybrid_retriever.remove_from_bm25_index_by_metadata_filter(
            tenant_id=tenant_id,
            metadata_filter={"chunk_id": {"$eq": str(chunk.id)}},
        )
    except Exception:
        bm25_error = "bm25 delete failed"

    if strictness == "strict" and (vector_error or bm25_error):
        await documents_module._record_chunk_index_drift(
            db=db,
            document=document,
            chunk=chunk,
            tenant_id=tenant_id,
            account_id=account_id,
            operation="chunk.disable",
            strictness=strictness,
            vector_error=vector_error,
            bm25_error=bm25_error,
        )
        raise HTTPException(
            status_code=409, detail="Index consistency strict mode blocked disable; drift item recorded"
        )

    if getattr(chunk, "disabled_at", None) is None:
        chunk.disabled_at = datetime.now(UTC)
    chunk.vector_id = None
    document.updated_at = datetime.now(UTC)

    await documents_module._record_chunk_index_drift(
        db=db,
        document=document,
        chunk=chunk,
        tenant_id=tenant_id,
        account_id=account_id,
        operation="chunk.disable",
        strictness=strictness,
        vector_error=vector_error,
        bm25_error=bm25_error,
    )

    documents_module.audit_log_event(
        db,
        tenant_id=tenant_id,
        actor_id=account_id,
        action="document.chunk.disable",
        resource_type="document",
        resource_id=str(document_id),
        details={
            "chunk_id": str(chunk.id),
            "chunk_index": int(getattr(chunk, "chunk_index", 0) or 0),
            "index_operation_success": not bool(vector_error or bm25_error),
            "index_consistency_strictness": strictness,
        },
    )
    db.commit()
    with contextlib.suppress(Exception):
        db.refresh(chunk)

    return chunk


@router.post(
    "/{document_id}/chunks/{chunk_id}/enable",
    response_model=DocumentChunkSchema,
    responses=documents_module._DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
def enable_document_chunk(
    document_id: uuid.UUID,
    chunk_id: uuid.UUID,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """Enable a previously-disabled chunk (requires re-embed to restore vector index)."""
    documents_module.DatasetService.ensure_member(db, tenant_id, account_id)

    document = documents_module._get_document_for_chunk_ops(db, tenant_id, document_id)
    if not document:
        raise HTTPException(status_code=404, detail=documents_module.DOC_NOT_FOUND_DETAIL)
    documents_module._assert_document_writable_for_chunk_ops(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        document=document,
    )

    current_status = str(getattr(document, "status", "") or "").lower()
    if current_status in {"pending", "processing"}:
        raise HTTPException(status_code=409, detail=f"Cannot edit chunks for a {current_status} document")

    chunk = documents_module._get_chunk_for_chunk_ops(db, tenant_id, document_id, chunk_id)
    if not chunk:
        raise HTTPException(status_code=404, detail=documents_module.CHUNK_NOT_FOUND_DETAIL)

    doc_meta = dict(getattr(document, "doc_metadata", None) or {})
    active_key = documents_module._resolve_active_doc_pipeline_key(document_id, doc_meta)
    chunk_key = str((getattr(chunk, "doc_metadata", None) or {}).get("doc_pipeline_key") or "").strip()
    if active_key and chunk_key and chunk_key != active_key:
        raise HTTPException(status_code=409, detail=documents_module.CHUNK_NOT_ACTIVE_PIPELINE_DETAIL)

    if getattr(chunk, "disabled_at", None) is not None:
        chunk.disabled_at = None
    document.updated_at = datetime.now(UTC)

    documents_module.audit_log_event(
        db,
        tenant_id=tenant_id,
        actor_id=account_id,
        action="document.chunk.enable",
        resource_type="document",
        resource_id=str(document_id),
        details={"chunk_id": str(chunk.id), "chunk_index": int(getattr(chunk, "chunk_index", 0) or 0)},
    )
    db.commit()
    with contextlib.suppress(Exception):
        db.refresh(chunk)

    return chunk


@router.post(
    "/{document_id}/chunks/reembed",
    response_model=DocumentChunkReembedResponse,
    responses=documents_module._DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
def reembed_document_chunks(
    document_id: uuid.UUID,
    payload: DocumentChunkReembedRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """Re-embed selected chunks (vector + BM25) best-effort."""
    document, active_key = _load_chunk_write_document(
        db=db,
        tenant_id=tenant_id,
        account_id=account_id,
        document_id=document_id,
        edit_verb="re-embed chunks",
    )
    reembedded = 0
    not_found: list[UUID] = []
    denied: list[UUID] = []
    conflicts: list[UUID] = []
    indexer = documents_module.Indexer(db)

    for chunk_id in payload.chunk_ids:
        chunk = documents_module._get_chunk_for_chunk_ops(db, tenant_id, document_id, chunk_id)
        if not chunk:
            not_found.append(chunk_id)
            continue
        if getattr(chunk, "disabled_at", None) is not None and not bool(payload.include_disabled):
            conflicts.append(chunk_id)
            continue
        chunk_key = str((getattr(chunk, "doc_metadata", None) or {}).get("doc_pipeline_key") or "").strip()
        if active_key and chunk_key and chunk_key != active_key:
            conflicts.append(chunk_id)
            continue
        if not _reembed_single_chunk(
            db=db,
            document=document,
            chunk=chunk,
            tenant_id=tenant_id,
            document_id=document_id,
            account_id=account_id,
            indexer=indexer,
        ):
            conflicts.append(chunk_id)
            continue
        reembedded += 1

    if reembedded:
        db.commit()

    return {
        "reembedded": reembedded,
        "not_found": not_found,
        "denied": denied,
        "conflicts": conflicts,
    }

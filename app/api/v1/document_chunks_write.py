import contextlib
import uuid
from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.api.schemas.document import (
    DocumentChunkCreateRequest,
    DocumentChunkReembedRequest,
    DocumentChunkReembedResponse,
    DocumentChunkSchema,
    DocumentChunkUpdateRequest,
)
from app.core.config import settings
from app.core.database import get_db
from app.models.document import Document as DBDocument
from app.models.document import DocumentChunk
from app.rag.core.logging import get_logger
from app.services import dataset_service
from app.services.audit_log_service import audit_log_event
from app.services.document_access_service import (
    assert_document_writable_for_lifecycle as _assert_document_writable_for_lifecycle,
)
from app.services.document_lifecycle_service import DOC_NOT_FOUND_DETAIL
from app.services.index_audit_service import _resolve_active_doc_pipeline_key, build_index_drift_marker
from app.services.indexer import Indexer

_DEFAULT_HTTP_EXCEPTION_RESPONSES = {
    400: {"description": "Bad Request"},
    403: {"description": "Forbidden"},
    404: {"description": "Not Found"},
    409: {"description": "Conflict"},
    416: {"description": "Range Not Satisfiable"},
}
CHUNK_NOT_FOUND_DETAIL = "Chunk not found"
CHUNK_NOT_ACTIVE_PIPELINE_DETAIL = "Chunk is not in the active pipeline version"
CHUNK_PATCH_OPERATION = "chunk.patch"

router = APIRouter(responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
logger = get_logger("api.documents")


def _get_document_for_chunk_ops(db: Session, tenant_id: UUID, document_id: UUID) -> DBDocument | None:
    return db.query(DBDocument).filter(DBDocument.id == document_id, DBDocument.tenant_id == tenant_id).first()


def _get_chunk_for_chunk_ops(
    db: Session,
    tenant_id: UUID,
    document_id: UUID,
    chunk_id: UUID,
) -> DocumentChunk | None:
    return (
        db.query(DocumentChunk)
        .filter(
            DocumentChunk.tenant_id == tenant_id,
            DocumentChunk.document_id == document_id,
            DocumentChunk.id == chunk_id,
        )
        .first()
    )


def _assert_document_writable_for_chunk_ops(
    db: Session,
    *,
    tenant_id: UUID,
    account_id: str,
    document: DBDocument,
) -> None:
    _assert_document_writable_for_lifecycle(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        document=document,
    )


def _normalize_index_consistency_strictness(*, patch_mode: bool = False) -> str:
    strictness = str(settings.INDEX_CONSISTENCY_STRICTNESS or "off").strip().lower()
    if strictness not in {"off", "warn", "strict"}:
        strictness = "off"
    enabled = bool(settings.INDEX_CONSISTENCY_ENABLED)
    patch_strict = bool(settings.INDEX_CONSISTENCY_PATCH_CHUNK_STRICT)
    if patch_mode and patch_strict:
        return "strict"
    if not enabled and strictness != "strict":
        return "off"
    return strictness


def _build_index_channel_result(
    *,
    status: str,
    attempted: bool,
    error: str | None = None,
    vector_id: str | None = None,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "status": str(status or "skipped"),
        "attempted": bool(attempted),
    }
    if error:
        out["error"] = str(error)[:240]
    if vector_id:
        out["vector_id"] = str(vector_id)[:200]
    return out


def _index_channel_status(value: dict[str, Any] | None) -> str:
    return str((value or {}).get("status") or "skipped").strip().lower()


def _index_drift_marker_rows(drift_markers: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    return [dict(marker) for marker in (drift_markers or []) if isinstance(marker, dict)][:20]


def _build_chunk_index_operation_result(
    *,
    operation: str,
    strictness: str,
    vector: dict[str, Any],
    bm25: dict[str, Any],
    kg: dict[str, Any] | None = None,
    reconcile: dict[str, Any] | None = None,
    drift_markers: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    vector_status = _index_channel_status(vector)
    bm25_status = _index_channel_status(bm25)
    kg_status = _index_channel_status(kg) if isinstance(kg, dict) else "skipped"
    success = all(st in {"ok", "skipped"} for st in (vector_status, bm25_status, kg_status))
    return {
        "schema": "mimirq.index_operation_result.v1",
        "operation": str(operation or "").strip()[:80] or CHUNK_PATCH_OPERATION,
        "strictness": str(strictness or "off").strip().lower(),
        "success": bool(success),
        "vector": dict(vector or {}),
        "bm25": dict(bm25 or {}),
        "kg": (dict(kg or {}) if isinstance(kg, dict) else None),
        "reconcile": (dict(reconcile or {}) if isinstance(reconcile, dict) else None),
        "drift_markers": _index_drift_marker_rows(drift_markers),
    }


def _persist_chunk_index_operation_result(
    *,
    db: Session,
    chunk: DocumentChunk,
    result: dict[str, Any],
    drift_markers: list[dict[str, Any]] | None = None,
) -> None:
    meta = dict(getattr(chunk, "doc_metadata", None) or {})
    meta["index_operation_result"] = dict(result or {})

    if drift_markers:
        existing = meta.get("index_drift_markers")
        existing_rows = [dict(x) for x in existing if isinstance(x, dict)] if isinstance(existing, list) else []
        merged = existing_rows + [dict(x) for x in drift_markers if isinstance(x, dict)]
        meta["index_drift_markers"] = merged[-20:]

    chunk.doc_metadata = meta
    db.commit()
    with contextlib.suppress(Exception):
        db.refresh(chunk)


async def _enqueue_index_drift_reconcile(
    *,
    tenant_id: UUID,
    document_id: UUID,
    requested_by: str,
) -> str | None:
    if not bool(settings.TASK_QUEUE_ENABLED):
        return None

    try:
        from app.tasks.queue import enqueue_rebuild_indexes

        return await enqueue_rebuild_indexes(
            tenant_id=tenant_id,
            document_id=document_id,
            requested_by=str(requested_by or "system:index-drift"),
            job_id=f"index-drift-reconcile:{tenant_id}:{document_id}",
        )
    except Exception:
        return None


def _build_chunk_drift_markers(
    *,
    operation: str,
    strictness: str,
    tenant_id: UUID,
    document_id: UUID,
    chunk: DocumentChunk,
    vector_error: str | None,
    bm25_error: str | None,
    emit_drift_markers: bool,
) -> list[dict[str, Any]]:
    drift_markers: list[dict[str, Any]] = []
    if emit_drift_markers and vector_error:
        drift_markers.append(
            build_index_drift_marker(
                operation=operation,
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
            build_index_drift_marker(
                operation=operation,
                strictness=strictness,
                tenant_id=tenant_id,
                document_id=document_id,
                chunk_id=chunk.id,
                channel="bm25",
                reason=bm25_error,
            )
        )
    return drift_markers


async def _record_chunk_index_drift(
    *,
    db: Session,
    document: DBDocument,
    chunk: DocumentChunk,
    tenant_id: UUID,
    account_id: str,
    operation: str,
    strictness: str,
    vector_error: str | None,
    bm25_error: str | None,
    vector_id_after: str | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]], str | None]:
    from app.services.index_audit_service import record_index_drift_item

    emit_drift_markers = bool(settings.INDEX_CONSISTENCY_EMIT_DRIFT_MARKERS)
    drift_markers = _build_chunk_drift_markers(
        operation=operation,
        strictness=strictness,
        tenant_id=tenant_id,
        document_id=document.id,
        chunk=chunk,
        vector_error=vector_error,
        bm25_error=bm25_error,
        emit_drift_markers=emit_drift_markers,
    )
    reconcile_task_id: str | None = None
    reconcile_result: dict[str, Any] | None = None
    auto_reconcile_supported = vector_error is None and bm25_error is not None
    if drift_markers and auto_reconcile_supported:
        reconcile_task_id = await _enqueue_index_drift_reconcile(
            tenant_id=tenant_id,
            document_id=document.id,
            requested_by=account_id,
        )
        if reconcile_task_id:
            reconcile_result = {
                "status": "enqueued",
                "scope": "document",
                "channels": ["bm25"],
                "task_id": reconcile_task_id,
            }
        else:
            reconcile_result = {
                "status": "not_enqueued",
                "scope": "document",
                "channels": ["bm25"],
                "reason": "queue_disabled_duplicate_or_unavailable",
            }
    elif drift_markers and vector_error is not None:
        reconcile_result = {
            "status": "unsupported",
            "reason": "document_scoped_auto_reconcile_only_supports_bm25",
        }
    elif drift_markers:
        reconcile_result = {
            "status": "skipped",
        }

    if drift_markers:
        for marker in drift_markers:
            with contextlib.suppress(Exception):
                record_index_drift_item(
                    db=db,
                    dataset_id=getattr(document, "dataset_id", None),
                    marker=marker,
                    reconcile_task_id=(reconcile_task_id if marker.get("channel") == "bm25" else None),
                )

    vector_result = _build_index_channel_result(
        status=("error" if vector_error else "ok"),
        attempted=True,
        error=vector_error,
        vector_id=vector_id_after,
    )
    bm25_result = _build_index_channel_result(
        status=("error" if bm25_error else "ok"),
        attempted=True,
        error=bm25_error,
    )
    operation_result = _build_chunk_index_operation_result(
        operation=operation,
        strictness=strictness,
        vector=vector_result,
        bm25=bm25_result,
        kg=None,
        reconcile=reconcile_result,
        drift_markers=drift_markers,
    )
    _persist_chunk_index_operation_result(
        db=db,
        chunk=chunk,
        result=operation_result,
        drift_markers=drift_markers,
    )
    return operation_result, drift_markers, reconcile_task_id


@router.post(
    "/{document_id}/chunks",
    response_model=DocumentChunkSchema,
    status_code=201,
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
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

    dataset_service.ensure_member(db, tenant_id, account_id)

    document = db.query(DBDocument).filter(DBDocument.id == document_id, DBDocument.tenant_id == tenant_id).first()
    if not document:
        raise HTTPException(status_code=404, detail=DOC_NOT_FOUND_DETAIL)

    _assert_document_writable_for_chunk_ops(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        document=document,
    )

    current_status = str(document.status or "").lower()
    if current_status in {"pending", "processing"}:
        raise HTTPException(status_code=409, detail=f"Cannot edit chunks for a {current_status} document")

    doc_meta = dict(getattr(document, "doc_metadata", None) or {})
    active_key = _resolve_active_doc_pipeline_key(document_id, doc_meta)
    active_hash = str(doc_meta.get("active_pipeline_hash") or doc_meta.get("pipeline_hash") or "").strip()

    query = db.query(func.max(DocumentChunk.chunk_index)).filter(
        DocumentChunk.tenant_id == tenant_id,
        DocumentChunk.document_id == document_id,
    )
    if active_key:
        query = query.filter(
            DocumentChunk.doc_metadata["doc_pipeline_key"].astext == active_key  # type: ignore[attr-defined]
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
    indexer = Indexer(db)
    try:
        vector_id = indexer.upsert_document_chunk_vector(
            document_id=document_id,
            tenant_id=tenant_id,
            content=payload.content,
            metadata=meta,
        )
    except Exception:
        vector_id = None

    chunk = DocumentChunk(
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
        Indexer(db)._update_bm25_for_chunks(
            db_chunks=[chunk],
            tenant_id=tenant_id,
            document_id=document_id,
            default_source=str(getattr(document, "filename", "") or "unknown"),
            enable_bm25=bool(getattr(settings, "BM25_INDEX_ENABLED", True)),
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "BM25 upsert failed for chunk %s: %s",
            str(getattr(chunk, "id", "") or "?"),
            str(exc)[:200],
        )

    try:
        stat_q = db.query(
            func.count(DocumentChunk.id),
            func.sum(func.length(DocumentChunk.content)),
        ).filter(
            DocumentChunk.tenant_id == tenant_id,
            DocumentChunk.document_id == document_id,
        )
        if active_key:
            stat_q = stat_q.filter(
                DocumentChunk.doc_metadata["doc_pipeline_key"].astext == active_key  # type: ignore[attr-defined]
            )
        cnt, total_chars = stat_q.first() or (None, None)
        document.chunk_count = int(cnt or 0)
        document.total_characters = int(total_chars or 0)
        db.commit()
    except Exception:
        db.rollback()

    audit_log_event(
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
    dataset_service.ensure_member(db, tenant_id, account_id)
    document = _get_document_for_chunk_ops(db, tenant_id, document_id)
    if not document:
        raise HTTPException(status_code=404, detail=DOC_NOT_FOUND_DETAIL)
    _assert_document_writable_for_chunk_ops(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        document=document,
    )
    current_status = str(getattr(document, "status", "") or "").lower()
    if current_status in {"pending", "processing"}:
        raise HTTPException(status_code=409, detail=f"Cannot {edit_verb} for a {current_status} document")
    doc_meta = dict(getattr(document, "doc_metadata", None) or {})
    active_key = _resolve_active_doc_pipeline_key(document_id, doc_meta)
    return document, active_key


def _get_active_chunk_or_404(
    *,
    db: Session,
    tenant_id: UUID,
    document_id: UUID,
    chunk_id: UUID,
    active_key: str | None,
):
    chunk = _get_chunk_for_chunk_ops(db, tenant_id, document_id, chunk_id)
    if not chunk:
        raise HTTPException(status_code=404, detail=CHUNK_NOT_FOUND_DETAIL)
    chunk_key = str((getattr(chunk, "doc_metadata", None) or {}).get("doc_pipeline_key") or "").strip()
    if active_key and chunk_key and chunk_key != active_key:
        raise HTTPException(status_code=409, detail=CHUNK_NOT_ACTIVE_PIPELINE_DETAIL)
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
    meta = dict(chunk.doc_metadata or {})
    for raw_key, value in payload.metadata.items():
        if not isinstance(raw_key, str) or not raw_key.strip():
            continue
        key = raw_key.strip()
        if value is None:
            meta.pop(key, None)
        else:
            meta[key] = value
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
    strictness = _normalize_index_consistency_strictness(patch_mode=True)
    emit_drift_markers = bool(getattr(settings, "INDEX_CONSISTENCY_EMIT_DRIFT_MARKERS", True))
    drift_markers: list[dict[str, Any]] = []
    vector_error: str | None = None
    bm25_error: str | None = None
    vector_id_after: str | None = None
    indexer = Indexer(db)

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
        Indexer(db)._update_bm25_for_chunks(
            db_chunks=[chunk],
            tenant_id=tenant_id,
            document_id=document_id,
            default_source=str(getattr(document, "filename", "") or "unknown"),
            enable_bm25=bool(getattr(settings, "BM25_INDEX_ENABLED", True)),
        )
    except Exception:
        bm25_error = "bm25 upsert failed"

    if emit_drift_markers and vector_error:
        drift_markers.append(
            build_index_drift_marker(
                operation=CHUNK_PATCH_OPERATION,
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
            build_index_drift_marker(
                operation=CHUNK_PATCH_OPERATION,
                strictness=strictness,
                tenant_id=tenant_id,
                document_id=document_id,
                chunk_id=chunk.id,
                channel="bm25",
                reason=bm25_error,
            )
        )

    operation_result = _build_chunk_index_operation_result(
        operation=CHUNK_PATCH_OPERATION,
        strictness=strictness,
        vector=_build_index_channel_result(
            status=("error" if vector_error else "ok"),
            attempted=True,
            error=vector_error,
            vector_id=vector_id_after,
        ),
        bm25=_build_index_channel_result(
            status=("error" if bm25_error else "ok"),
            attempted=True,
            error=bm25_error,
        ),
        kg=None,
        drift_markers=drift_markers,
    )
    _persist_chunk_index_operation_result(
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

    strictness = _normalize_index_consistency_strictness(patch_mode=False)
    vector_error: str | None = None
    bm25_error: str | None = None
    indexer = Indexer(db)
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
        await _record_chunk_index_drift(
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
            func.count(DocumentChunk.id),
            func.sum(func.length(DocumentChunk.content)),
        ).filter(
            DocumentChunk.tenant_id == tenant_id,
            DocumentChunk.document_id == document_id,
        )
        if active_key:
            stat_q = stat_q.filter(
                DocumentChunk.doc_metadata["doc_pipeline_key"].astext == active_key  # type: ignore[attr-defined]
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

        Indexer(db).delete_event_indexes_for_chunks(
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
        logger.debug("Vector filtered delete failed for chunk %s: %s", str(chunk.id), str(exc)[:160])

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
        bm25_doc = DBDocument(
            page_content=str(getattr(chunk, "content", "") or ""),
            id=str(chunk.id),
            metadata=bm25_meta,
        )
        hybrid_retriever.upsert_bm25_documents([bm25_doc], tenant_id=tenant_id, db=db)
    except Exception as exc:  # noqa: BLE001
        logger.debug("BM25 upsert failed for chunk %s: %s", str(chunk.id), str(exc)[:160])

    audit_log_event(
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
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
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

    audit_log_event(
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
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
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
    audit_log_event(
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
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
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

    dataset_service.ensure_member(db, tenant_id, account_id)

    document = _get_document_for_chunk_ops(db, tenant_id, document_id)
    if not document:
        raise HTTPException(status_code=404, detail=DOC_NOT_FOUND_DETAIL)
    _assert_document_writable_for_chunk_ops(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        document=document,
    )

    current_status = str(getattr(document, "status", "") or "").lower()
    if current_status in {"pending", "processing"}:
        raise HTTPException(status_code=409, detail=f"Cannot edit chunks for a {current_status} document")

    chunk = _get_chunk_for_chunk_ops(db, tenant_id, document_id, chunk_id)
    if not chunk:
        raise HTTPException(status_code=404, detail=CHUNK_NOT_FOUND_DETAIL)

    doc_meta = dict(getattr(document, "doc_metadata", None) or {})
    active_key = _resolve_active_doc_pipeline_key(document_id, doc_meta)
    chunk_key = str((getattr(chunk, "doc_metadata", None) or {}).get("doc_pipeline_key") or "").strip()
    if active_key and chunk_key and chunk_key != active_key:
        raise HTTPException(status_code=409, detail=CHUNK_NOT_ACTIVE_PIPELINE_DETAIL)

    strictness = _normalize_index_consistency_strictness(patch_mode=False)
    vector_error: str | None = None
    bm25_error: str | None = None

    indexer = Indexer(db)
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
        await _record_chunk_index_drift(
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

    await _record_chunk_index_drift(
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

    audit_log_event(
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
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
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
    dataset_service.ensure_member(db, tenant_id, account_id)

    document = _get_document_for_chunk_ops(db, tenant_id, document_id)
    if not document:
        raise HTTPException(status_code=404, detail=DOC_NOT_FOUND_DETAIL)
    _assert_document_writable_for_chunk_ops(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        document=document,
    )

    current_status = str(getattr(document, "status", "") or "").lower()
    if current_status in {"pending", "processing"}:
        raise HTTPException(status_code=409, detail=f"Cannot edit chunks for a {current_status} document")

    chunk = _get_chunk_for_chunk_ops(db, tenant_id, document_id, chunk_id)
    if not chunk:
        raise HTTPException(status_code=404, detail=CHUNK_NOT_FOUND_DETAIL)

    doc_meta = dict(getattr(document, "doc_metadata", None) or {})
    active_key = _resolve_active_doc_pipeline_key(document_id, doc_meta)
    chunk_key = str((getattr(chunk, "doc_metadata", None) or {}).get("doc_pipeline_key") or "").strip()
    if active_key and chunk_key and chunk_key != active_key:
        raise HTTPException(status_code=409, detail=CHUNK_NOT_ACTIVE_PIPELINE_DETAIL)

    if getattr(chunk, "disabled_at", None) is not None:
        chunk.disabled_at = None
    document.updated_at = datetime.now(UTC)

    audit_log_event(
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
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
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
    indexer = Indexer(db)

    for chunk_id in payload.chunk_ids:
        chunk = _get_chunk_for_chunk_ops(db, tenant_id, document_id, chunk_id)
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

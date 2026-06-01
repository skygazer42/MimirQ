from __future__ import annotations

import contextlib
import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.document import Document as DBDocument
from app.models.document import DocumentChunk
from app.models.index_drift_item import IndexDriftItem
from app.services.dataset_service import DatasetService


def _now_utc_iso() -> str:
    return datetime.now(UTC).isoformat()


def build_index_drift_marker(
    *,
    operation: str,
    strictness: str,
    tenant_id: UUID | str | None,
    document_id: UUID | str | None,
    chunk_id: UUID | str | None,
    channel: str,
    reason: str,
    details: dict[str, Any] | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema": "mimirq.index_drift_marker.v1",
        "created_at": str(created_at or _now_utc_iso()),
        "operation": str(operation or "").strip()[:80],
        "strictness": str(strictness or "").strip().lower()[:20] or "off",
        "tenant_id": str(tenant_id) if tenant_id is not None else None,
        "document_id": str(document_id) if document_id is not None else None,
        "chunk_id": str(chunk_id) if chunk_id is not None else None,
        "channel": str(channel or "").strip().lower()[:40] or "unknown",
        "reason": str(reason or "").strip()[:240] or "index_operation_failed",
    }
    if isinstance(details, dict) and details:
        safe_details: dict[str, Any] = {}
        for key, value in details.items():
            k = str(key or "").strip()
            if not k:
                continue
            if isinstance(value, (bool, int, float)) or value is None:
                safe_details[k[:80]] = value
            else:
                safe_details[k[:80]] = str(value)[:200]
            if len(safe_details) >= 20:
                break
        if safe_details:
            payload["details"] = safe_details
    return payload


def _uuid_or_none(value: UUID | str | None) -> UUID | None:
    if value is None:
        return None
    try:
        return UUID(str(value))
    except Exception:
        return None


def record_index_drift_item(
    *,
    db: Session,
    dataset_id: UUID | str | None,
    marker: dict[str, Any],
    reconcile_task_id: str | None = None,
) -> IndexDriftItem:
    if not isinstance(marker, dict):
        raise ValueError("marker must be an object")

    item = IndexDriftItem(
        tenant_id=_uuid_or_none(marker.get("tenant_id")),
        dataset_id=_uuid_or_none(dataset_id),
        document_id=_uuid_or_none(marker.get("document_id")),
        chunk_id=_uuid_or_none(marker.get("chunk_id")),
        operation=str(marker.get("operation") or "").strip()[:80] or "unknown",
        channel=str(marker.get("channel") or "").strip().lower()[:40] or "unknown",
        strictness=str(marker.get("strictness") or "off").strip().lower()[:20] or "off",
        status="open",
        reason=str(marker.get("reason") or "").strip()[:240] or "index_operation_failed",
        details=dict(marker.get("details") or {}) if isinstance(marker.get("details"), dict) else {},
        marker=dict(marker),
        reconcile_task_id=str(reconcile_task_id or "").strip() or None,
        replay_count=0,
    )
    if item.tenant_id is None:
        raise ValueError("marker.tenant_id is required")

    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def list_index_drift_items(
    *,
    db: Session,
    tenant_id: UUID | str,
    dataset_id: UUID | str | None = None,
    status: str = "open",
    limit: int = 100,
) -> list[IndexDriftItem]:
    tenant_uuid = _uuid_or_none(tenant_id)
    if tenant_uuid is None:
        return []

    cap = max(1, min(int(limit or 0), 500))
    q = db.query(IndexDriftItem).filter(IndexDriftItem.tenant_id == tenant_uuid)
    dataset_uuid = _uuid_or_none(dataset_id)
    if dataset_uuid is not None:
        q = q.filter(IndexDriftItem.dataset_id == dataset_uuid)

    state = str(status or "open").strip().lower()
    if state in {"open", "resolved"}:
        q = q.filter(IndexDriftItem.status == state)

    return (
        q.order_by(
            IndexDriftItem.created_at.desc().nullslast(),  # type: ignore[attr-defined]
            IndexDriftItem.id.desc(),
        )
        .limit(cap)
        .all()
    )


def resolve_index_drift_item(
    *,
    db: Session,
    tenant_id: UUID | str,
    item_id: UUID | str,
    resolved_by: str,
    resolution_note: str = "",
) -> IndexDriftItem | None:
    tenant_uuid = _uuid_or_none(tenant_id)
    drift_uuid = _uuid_or_none(item_id)
    if tenant_uuid is None or drift_uuid is None:
        return None

    item = (
        db.query(IndexDriftItem)
        .filter(
            IndexDriftItem.tenant_id == tenant_uuid,
            IndexDriftItem.id == drift_uuid,
        )
        .first()
    )
    if item is None:
        return None

    item.status = "resolved"
    item.resolved_at = datetime.now(UTC)
    item.resolved_by = str(resolved_by or "").strip()[:255] or None
    item.resolution_note = str(resolution_note or "").strip()[:2000] or None
    db.commit()
    db.refresh(item)
    return item


def _resolve_active_doc_pipeline_key(document_id: UUID, doc_metadata: dict[str, Any]) -> str:
    active_hash = str((doc_metadata or {}).get("active_pipeline_hash") or (doc_metadata or {}).get("pipeline_hash") or "").strip()
    return f"{document_id}:{active_hash}" if active_hash else str(document_id)


def _load_index_drift_context(
    *,
    db: Session,
    item: IndexDriftItem,
) -> tuple[DBDocument | None, DocumentChunk | None]:
    document = None
    chunk = None

    if getattr(item, "document_id", None) is not None:
        document = (
            db.query(DBDocument)
            .filter(
                DBDocument.tenant_id == item.tenant_id,
                DBDocument.id == item.document_id,
            )
            .first()
        )

    if getattr(item, "document_id", None) is not None and getattr(item, "chunk_id", None) is not None:
        chunk = (
            db.query(DocumentChunk)
            .filter(
                DocumentChunk.tenant_id == item.tenant_id,
                DocumentChunk.document_id == item.document_id,
                DocumentChunk.id == item.chunk_id,
            )
            .first()
        )

    return document, chunk


def _count_open_index_drift_siblings(
    *,
    db: Session,
    item: IndexDriftItem,
) -> int:
    return int(
        db.query(func.count(IndexDriftItem.id))
        .filter(
            IndexDriftItem.tenant_id == item.tenant_id,
            IndexDriftItem.document_id == item.document_id,
            IndexDriftItem.chunk_id == item.chunk_id,
            IndexDriftItem.operation == item.operation,
            IndexDriftItem.status == "open",
            IndexDriftItem.id != item.id,
        )
        .scalar()
        or 0
    )


def _refresh_document_chunk_stats(*, db: Session, document: DBDocument) -> None:
    active_key = _resolve_active_doc_pipeline_key(document.id, dict(getattr(document, "doc_metadata", None) or {}))
    q = db.query(func.count(DocumentChunk.id), func.sum(func.length(DocumentChunk.content))).filter(
        DocumentChunk.tenant_id == document.tenant_id,
        DocumentChunk.document_id == document.id,
    )
    if active_key:
        q = q.filter(DocumentChunk.doc_metadata["doc_pipeline_key"].astext == active_key)  # type: ignore[attr-defined]
    cnt, total_chars = q.first() or (None, None)
    document.chunk_count = int(cnt or 0)
    document.total_characters = int(total_chars or 0)
    db.commit()


def _replay_vector_patch(*, db: Session, item: IndexDriftItem, chunk: DocumentChunk) -> None:
    from app.storage.vector.factory import get_vector_store

    if item.document_id is None or item.chunk_id is None:
        raise ValueError("chunk.patch vector replay requires document_id and chunk_id")

    store = get_vector_store()
    store.delete_by_document_id_and_filter(
        document_id=item.document_id,
        tenant_id=item.tenant_id,
        metadata_filter={"chunk_id": {"$eq": str(item.chunk_id)}},
    )
    ids = list(
        store.add_documents(
            [{"content": str(getattr(chunk, "content", "") or ""), "metadata": dict(getattr(chunk, "doc_metadata", None) or {})}],
            item.document_id,
            item.tenant_id,
        )
    )
    if ids and ids[0]:
        chunk.vector_id = str(ids[0])
    db.commit()


def _replay_bm25_patch(*, db: Session, item: IndexDriftItem, document: DBDocument, chunk: DocumentChunk) -> None:
    from app.services.indexer import Indexer

    if item.document_id is None:
        raise ValueError("chunk.patch bm25 replay requires document_id")

    Indexer(db)._update_bm25_for_chunks(
        db_chunks=[chunk],
        tenant_id=item.tenant_id,
        document_id=item.document_id,
        default_source=str(getattr(document, "filename", "") or "unknown"),
        enable_bm25=bool(getattr(settings, "BM25_INDEX_ENABLED", True)),
    )


def _replay_vector_delete(*, item: IndexDriftItem) -> None:
    from app.storage.vector.factory import get_vector_store

    if item.document_id is None or item.chunk_id is None:
        raise ValueError("vector delete replay requires document_id and chunk_id")

    get_vector_store().delete_by_document_id_and_filter(
        document_id=item.document_id,
        tenant_id=item.tenant_id,
        metadata_filter={"chunk_id": {"$eq": str(item.chunk_id)}},
    )


def _replay_bm25_delete(*, item: IndexDriftItem) -> None:
    from app.rag.retriever import hybrid_retriever

    if item.chunk_id is None:
        raise ValueError("bm25 delete replay requires chunk_id")

    hybrid_retriever.remove_from_bm25_index_by_metadata_filter(
        tenant_id=item.tenant_id,
        metadata_filter={"chunk_id": {"$eq": str(item.chunk_id)}},
    )


def _finalize_chunk_disable(*, db: Session, chunk: DocumentChunk | None) -> None:
    if chunk is None:
        return
    if getattr(chunk, "disabled_at", None) is None:
        chunk.disabled_at = datetime.now(UTC)
    with contextlib.suppress(Exception):
        chunk.vector_id = None
    db.commit()


def _finalize_chunk_delete(
    *,
    db: Session,
    tenant_id: UUID,
    chunk_id: UUID | None,
    document: DBDocument | None,
    chunk: DocumentChunk | None,
) -> None:
    if chunk_id is not None:
        try:
            from app.rag.kg.models import KgRelation

            db.query(KgRelation).filter(
                KgRelation.tenant_id == tenant_id,
                KgRelation.chunk_id == chunk_id,
            ).delete(synchronize_session=False)
        except Exception:
            db.rollback()
            raise

        try:
            from app.services.indexer import Indexer

            Indexer(db).delete_event_indexes_for_chunks(
                tenant_id=tenant_id,
                chunk_ids=[chunk_id],
                commit=False,
                prune_orphan_entities=True,
            )
        except Exception:
            db.rollback()
            raise

    if chunk is not None:
        db.delete(chunk)
    db.commit()

    if document is not None:
        _refresh_document_chunk_stats(db=db, document=document)


def _replay_index_drift_item(
    *,
    db: Session,
    item: IndexDriftItem,
) -> str:
    document, chunk = _load_index_drift_context(db=db, item=item)
    operation = str(getattr(item, "operation", "") or "").strip().lower()
    channel = str(getattr(item, "channel", "") or "").strip().lower()

    if operation == "chunk.patch":
        if document is None or chunk is None or getattr(chunk, "disabled_at", None) is not None:
            return "resolved obsolete patch drift item"
        if channel == "vector":
            _replay_vector_patch(db=db, item=item, chunk=chunk)
            return "replayed vector patch indexing"
        if channel == "bm25":
            _replay_bm25_patch(db=db, item=item, document=document, chunk=chunk)
            return "replayed bm25 patch indexing"
        raise ValueError(f"unsupported chunk.patch drift channel: {channel}")

    if operation == "chunk.disable":
        if channel == "vector":
            _replay_vector_delete(item=item)
        elif channel == "bm25":
            _replay_bm25_delete(item=item)
        else:
            raise ValueError(f"unsupported chunk.disable drift channel: {channel}")

        if _count_open_index_drift_siblings(db=db, item=item) == 0:
            _finalize_chunk_disable(db=db, chunk=chunk)
        return "replayed disable drift item"

    if operation == "chunk.delete":
        if channel == "vector":
            _replay_vector_delete(item=item)
        elif channel == "bm25":
            _replay_bm25_delete(item=item)
        else:
            raise ValueError(f"unsupported chunk.delete drift channel: {channel}")

        if _count_open_index_drift_siblings(db=db, item=item) == 0:
            _finalize_chunk_delete(
                db=db,
                tenant_id=item.tenant_id,
                chunk_id=getattr(item, "chunk_id", None),
                document=document,
                chunk=chunk,
            )
        return "replayed delete drift item"

    raise ValueError(f"unsupported index drift operation: {operation}")


def replay_index_drift_items(
    *,
    db: Session,
    tenant_id: UUID | str,
    dataset_id: UUID | str | None = None,
    limit: int = 50,
    execute: bool = False,
    requested_by: str = "system:index-drift",
) -> dict[str, Any]:
    tenant_uuid = _uuid_or_none(tenant_id)
    dataset_uuid = _uuid_or_none(dataset_id)
    items = list_index_drift_items(
        db=db,
        tenant_id=tenant_uuid if tenant_uuid is not None else str(tenant_id),
        dataset_id=dataset_uuid,
        status="open",
        limit=limit,
    )

    queued_task_id: str | None = None
    attempted_ids: list[str] = []
    resolved_ids: list[str] = []
    replay_results: list[dict[str, Any]] = []
    if execute and items:
        for item in items:
            item_id = str(item.id)
            item.replay_count = int(getattr(item, "replay_count", 0) or 0) + 1
            item.last_replayed_at = datetime.now(UTC)
            db.commit()

            attempted_ids.append(item_id)
            try:
                note = _replay_index_drift_item(db=db, item=item)
                resolved = resolve_index_drift_item(
                    db=db,
                    tenant_id=item.tenant_id,
                    item_id=item.id,
                    resolved_by=str(requested_by or "system:index-drift"),
                    resolution_note=note,
                )
                if resolved is not None:
                    resolved_ids.append(item_id)
                replay_results.append({"id": item_id, "status": "resolved", "note": note})
            except Exception as exc:
                with contextlib.suppress(Exception):
                    db.rollback()
                replay_results.append(
                    {
                        "id": item_id,
                        "status": "open",
                        "error": f"{type(exc).__name__}: {str(exc)[:240]}",
                    }
                )

    return {
        "schema": "mimirq.index_drift_replay.v1",
        "tenant_id": str(tenant_uuid or tenant_id),
        "dataset_id": str(dataset_uuid) if dataset_uuid is not None else None,
        "execute": bool(execute),
        "limit": max(1, min(int(limit or 0), 500)),
        "selected_ids": [str(item.id) for item in items],
        "attempted_ids": attempted_ids,
        "resolved_ids": resolved_ids,
        "results": replay_results,
        "queued_task_id": str(queued_task_id) if queued_task_id else None,
    }


def compute_index_audit_summary(
    *,
    tenant_id: UUID,
    dataset_id: UUID,
    active_documents: int,
    active_chunks: int,
    vector_id_missing: int,
    vector_ids_checked: list[str],
    vector_ids_existing: set[str] | None,
    milvus_ids_sample: list[str] | None = None,
    active_chunk_ids_present: set[str] | None = None,
    sample_limit: int = 20,
) -> dict[str, Any]:
    """
    Pure helper: turn raw counts + id sets into a JSON-safe audit payload.

    This is intended for unit tests and for keeping the API handler thin.
    """
    cap = max(0, int(sample_limit or 0))

    checked = [str(x) for x in (vector_ids_checked or []) if str(x).strip()]
    existing = {str(x) for x in (vector_ids_existing or set()) if str(x).strip()}

    missing_in_vector = [vid for vid in checked if vid not in existing] if checked else []
    missing_in_vector_sorted = sorted(set(missing_in_vector))

    orphan_sample: list[str] = []
    if milvus_ids_sample and active_chunk_ids_present is not None:
        orphan_sample = [str(x) for x in milvus_ids_sample if str(x) not in active_chunk_ids_present]
        orphan_sample = sorted(set(orphan_sample))

    def _sample(values: list[str]) -> list[str]:
        if cap <= 0:
            return []
        return values[:cap]

    return {
        "tenant_id": str(tenant_id),
        "dataset_id": str(dataset_id),
        "vector_backend": str(getattr(settings, "VECTOR_BACKEND", "") or ""),
        "active_documents": int(active_documents),
        "active_chunks": int(active_chunks),
        "vector_id_missing": int(vector_id_missing),
        "vector_ids_checked": len(checked),
        "vector_ids_missing_in_backend": len(missing_in_vector_sorted),
        "vector_ids_missing_in_backend_sample": _sample(missing_in_vector_sorted),
        "milvus_ids_sampled": int(len(milvus_ids_sample or [])),
        "milvus_orphan_ids_sample": _sample(orphan_sample),
    }


def run_dataset_index_audit(
    *,
    db: Session,
    tenant_id: UUID,
    account_id: str,
    dataset_id: UUID,
    max_check_ids: int = 5000,
    milvus_list_limit: int = 2000,
    sample_limit: int = 20,
) -> dict[str, Any]:
    """
    Dataset-scoped index audit (admin-only entry point).

    This is best-effort by design:
    - It should never hard-fail the request due to vector backend errors.
    - It is bounded (max_check_ids / milvus_list_limit) to avoid massive scans.
    """
    # Ensure the caller is at least a tenant member; the API layer enforces admin role separately.
    DatasetService.ensure_member(db, tenant_id, account_id)
    DatasetService.get_dataset(db, tenant_id, dataset_id)
    return _run_dataset_index_audit_core(
        db=db,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        max_check_ids=max_check_ids,
        milvus_list_limit=milvus_list_limit,
        sample_limit=sample_limit,
    )


def run_dataset_index_audit_internal(
    *,
    db: Session,
    tenant_id: UUID,
    dataset_id: UUID,
    max_check_ids: int = 5000,
    milvus_list_limit: int = 2000,
    sample_limit: int = 20,
) -> dict[str, Any]:
    """
    Dataset-scoped index audit intended for internal automation (cron / jobs).

    Differences vs `run_dataset_index_audit`:
    - does NOT require an account_id / membership check
    - still validates the dataset exists for the tenant
    """
    DatasetService.get_dataset(db, tenant_id, dataset_id)
    return _run_dataset_index_audit_core(
        db=db,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        max_check_ids=max_check_ids,
        milvus_list_limit=milvus_list_limit,
        sample_limit=sample_limit,
    )


def _run_dataset_index_audit_core(
    *,
    db: Session,
    tenant_id: UUID,
    dataset_id: UUID,
    max_check_ids: int,
    milvus_list_limit: int,
    sample_limit: int,
) -> dict[str, Any]:
    # "Active" documents: searchable in RAG (mirrors retrieval readiness checks).
    doc_ready_clause = or_(
        DBDocument.status == "completed",
        (DBDocument.doc_metadata["active_pipeline_ready"].astext == "true"),  # type: ignore[attr-defined]
    )
    docs_q = (
        db.query(DBDocument.id, DBDocument.doc_metadata)
        .filter(
            DBDocument.tenant_id == tenant_id,
            DBDocument.dataset_id == dataset_id,
            DBDocument.archived_at.is_(None),
            DBDocument.disabled_at.is_(None),
        )
        .filter(doc_ready_clause)
    )

    active_doc_ids = [row[0] for row in docs_q.all() if row and row[0]]
    active_documents = len(active_doc_ids)

    # Active pipeline hash: chunks must match this version to be considered "active".
    doc_active_hash = func.coalesce(
        DBDocument.doc_metadata["active_pipeline_hash"].astext,  # type: ignore[attr-defined]
        DBDocument.doc_metadata["pipeline_hash"].astext,  # type: ignore[attr-defined]
        "",
    )
    chunk_hash = func.coalesce(
        DocumentChunk.doc_metadata["pipeline_hash"].astext,  # type: ignore[attr-defined]
        "",
    )

    chunks_q = (
        db.query(DocumentChunk.id, DocumentChunk.vector_id)
        .join(
            DBDocument,
            and_(
                DBDocument.id == DocumentChunk.document_id,
                DBDocument.tenant_id == DocumentChunk.tenant_id,
            ),
        )
        .filter(
            DBDocument.tenant_id == tenant_id,
            DBDocument.dataset_id == dataset_id,
            DBDocument.archived_at.is_(None),
            DBDocument.disabled_at.is_(None),
        )
        .filter(doc_ready_clause)
        .filter(DocumentChunk.disabled_at.is_(None))
        .filter(chunk_hash == doc_active_hash)
    )

    active_chunks = int(
        chunks_q.with_entities(func.count(DocumentChunk.id)).scalar()  # type: ignore[arg-type]
        or 0
    )

    vector_id_missing = int(
        chunks_q.filter(or_(DocumentChunk.vector_id.is_(None), DocumentChunk.vector_id == ""))
        .with_entities(func.count(DocumentChunk.id))
        .scalar()  # type: ignore[arg-type]
        or 0
    )

    cap_check = max(0, int(max_check_ids or 0))
    if cap_check <= 0:
        cap_check = 5000

    vec_rows = (
        chunks_q.filter(DocumentChunk.vector_id.isnot(None))
        .with_entities(DocumentChunk.vector_id)
        .order_by(DocumentChunk.updated_at.desc().nullslast())  # type: ignore[attr-defined]
        .limit(cap_check)
        .all()
    )
    vector_ids_checked = [str(row[0]) for row in vec_rows if row and row[0]]

    vector_ids_existing: set[str] | None = None
    milvus_ids_sample: list[str] | None = None
    active_chunk_ids_present: set[str] | None = None

    vector_backend = str(getattr(settings, "VECTOR_BACKEND", "milvus") or "milvus").strip().lower()
    if vector_backend == "milvus" and vector_ids_checked:
        try:
            from app.storage.vector.milvus import milvus_store

            vector_ids_existing = milvus_store.fetch_existing_ids(vector_ids_checked)
        except Exception:
            vector_ids_existing = None

    # Orphan sample: list a bounded set of Milvus ids for the dataset and check if DB contains them.
    if vector_backend == "milvus" and int(milvus_list_limit or 0) > 0:
        try:
            from app.storage.vector.milvus import milvus_store

            milvus_ids_sample = milvus_store.list_ids_by_dataset(
                tenant_id=tenant_id,
                dataset_id=dataset_id,
                limit=max(0, int(milvus_list_limit or 0)),
                offset=0,
            )
        except Exception:
            milvus_ids_sample = None

    if milvus_ids_sample:
        # Only UUID-like ids can map back to DocumentChunk.id.
        want: list[UUID] = []
        for raw in milvus_ids_sample:
            try:
                want.append(UUID(str(raw)))
            except Exception:
                logging.getLogger(__name__).debug("Skipping item after non-critical exception", exc_info=True)
                continue

        if want:
            rows = chunks_q.filter(DocumentChunk.id.in_(want)).with_entities(DocumentChunk.id).all()
            active_chunk_ids_present = {str(r[0]) for r in rows if r and r[0]}
        else:
            active_chunk_ids_present = set()

    return compute_index_audit_summary(
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        active_documents=active_documents,
        active_chunks=active_chunks,
        vector_id_missing=vector_id_missing,
        vector_ids_checked=vector_ids_checked,
        vector_ids_existing=vector_ids_existing,
        milvus_ids_sample=milvus_ids_sample,
        active_chunk_ids_present=active_chunk_ids_present,
        sample_limit=sample_limit,
    )


__all__ = [
    "build_index_drift_marker",
    "compute_index_audit_summary",
    "list_index_drift_items",
    "record_index_drift_item",
    "replay_index_drift_items",
    "resolve_index_drift_item",
    "run_dataset_index_audit",
    "run_dataset_index_audit_internal",
]

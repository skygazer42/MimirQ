
import contextlib
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.document import Document as DBDocument
from app.models.document import DocumentChunk
from app.models.document_index_channel import DocumentIndexChannel
from app.models.index_drift_item import IndexDriftItem
from app.rag.core.logging import get_logger
from app.services.dataset_service import DatasetService
from app.services.document_index_channel_service import (
    DOCUMENT_INDEX_CHANNEL_TERMINAL_ERROR,
    DOCUMENT_INDEX_CHANNEL_TERMINAL_READY,
    DOCUMENT_INDEX_CHANNELS,
    summarize_document_index_channels,
)
from app.services.pipeline_config import resolve_pipeline_effective

_DEFAULT_INDEX_AUDIT_RECONCILE_SCAN_LIMIT = 100
_MAX_INDEX_AUDIT_RECONCILE_SCAN_LIMIT = 200


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


def _finalize_chunk_disable(
    *,
    db: Session,
    document: DBDocument | None,
    chunk: DocumentChunk | None,
) -> None:
    if chunk is None:
        return
    if getattr(chunk, "disabled_at", None) is None:
        chunk.disabled_at = datetime.now(UTC)
    with contextlib.suppress(Exception):
        chunk.vector_id = None
    if document is not None:
        document.updated_at = datetime.now(UTC)
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


def _replay_chunk_drift_delete(*, channel: str, item: IndexDriftItem) -> None:
    if channel == "vector":
        _replay_vector_delete(item=item)
        return
    if channel == "bm25":
        _replay_bm25_delete(item=item)
        return
    raise ValueError(f"unsupported chunk drift channel: {channel}")


def _finalize_chunk_drift_replay(
    *,
    db: Session,
    item: IndexDriftItem,
    operation: str,
    document: Any,
    chunk: Any,
) -> str:
    if _count_open_index_drift_siblings(db=db, item=item) != 0:
        return "replayed disable drift item" if operation == "chunk.disable" else "replayed delete drift item"
    if operation == "chunk.disable":
        _finalize_chunk_disable(db=db, document=document, chunk=chunk)
        return "replayed disable drift item"
    _finalize_chunk_delete(
        db=db,
        tenant_id=item.tenant_id,
        chunk_id=getattr(item, "chunk_id", None),
        document=document,
        chunk=chunk,
    )
    return "replayed delete drift item"


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

    if operation in {"chunk.disable", "chunk.delete"}:
        _replay_chunk_drift_delete(channel=channel, item=item)
        return _finalize_chunk_drift_replay(
            db=db,
            item=item,
            operation=operation,
            document=document,
            chunk=chunk,
        )

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
    index_channels: dict[str, Any] | None = None,
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
        "index_channels": dict(index_channels or {}),
    }


def _document_pipeline_hash(document: Any) -> str | None:
    meta = dict(getattr(document, "doc_metadata", None) or {})
    return str(meta.get("active_pipeline_hash") or meta.get("pipeline_hash") or "").strip() or None


def _document_channel_flags(document: Any) -> dict[str, bool]:
    effective = resolve_pipeline_effective(document_metadata=dict(getattr(document, "doc_metadata", None) or {}))
    return {
        "vector": bool(getattr(effective, "chunk_vector_enabled", False)),
        "bm25": bool(getattr(effective, "bm25_index_enabled", False)),
        "kg": bool(getattr(effective, "kg_enabled", False)),
        "event_vector": bool(getattr(effective, "event_vector_enabled", False)),
        "entity_vector": bool(getattr(effective, "entity_vector_enabled", False)),
    }


def _legacy_index_channel_status(document: Any, *, channel: str, enabled: bool) -> dict[str, Any]:
    status_raw = str(getattr(document, "status", "") or "").strip().lower()
    meta = dict(getattr(document, "doc_metadata", None) or {})
    active_ready = bool(meta.get("active_pipeline_ready")) or status_raw == "completed"

    if not enabled:
        status = "disabled"
    elif active_ready:
        status = "ready"
    elif status_raw in {"failed", "quarantined", "cancelled"}:
        status = "error"
    elif status_raw in {"processing"}:
        status = "processing"
    else:
        status = "pending"

    error = None
    if status == "error":
        error = str(getattr(document, "error_message", "") or meta.get("error_message") or "").strip() or None

    return {
        "channel": channel,
        "required": bool(enabled),
        "enabled": bool(enabled),
        "status": status,
        "error": error,
        "legacy": True,
    }


def _row_index_channel_status(row: Any) -> dict[str, Any]:
    return {
        "channel": str(getattr(row, "channel", "") or ""),
        "required": bool(getattr(row, "required", False)),
        "enabled": bool(getattr(row, "enabled", False)),
        "status": str(getattr(row, "status", "pending") or "pending").strip().lower(),
        "error": str(getattr(row, "error", "") or "").strip() or None,
        "legacy": False,
    }


def _index_channel_rows_by_document(
    *,
    documents: list[Any],
    channel_rows: list[Any],
) -> tuple[dict[str, dict[str, dict[str, Any]]], set[str]]:
    rows_by_document: dict[str, dict[str, dict[str, Any]]] = {}
    rows_seen_by_document: set[str] = set()
    pipeline_hash_by_document = {
        str(getattr(document, "id", "") or ""): _document_pipeline_hash(document)
        for document in documents
        if getattr(document, "id", None) is not None
    }
    for row in channel_rows:
        document_key = str(getattr(row, "document_id", "") or "")
        if not document_key:
            continue
        pipeline_hash = str(getattr(row, "pipeline_hash", "") or "").strip() or None
        if pipeline_hash != pipeline_hash_by_document.get(document_key):
            continue
        rows_seen_by_document.add(document_key)
        rows_by_document.setdefault(document_key, {})[str(getattr(row, "channel", "") or "")] = _row_index_channel_status(row)
    return rows_by_document, rows_seen_by_document


def _empty_index_channel_audit_summary() -> dict[str, Any]:
    return {
        "documents_with_channel_rows": 0,
        "documents_using_legacy_fallback": 0,
        "ready_documents": 0,
        "required_pending_documents": 0,
        "required_error_documents": 0,
        "optional_disabled_documents": 0,
        "optional_skipped_documents": 0,
        "status_counts": {},
        "status_counts_by_channel": {channel: {} for channel in DOCUMENT_INDEX_CHANNELS},
        "legacy_by_channel": {channel: 0 for channel in DOCUMENT_INDEX_CHANNELS},
        "required_pending_by_channel": {channel: 0 for channel in DOCUMENT_INDEX_CHANNELS},
        "required_error_by_channel": {channel: 0 for channel in DOCUMENT_INDEX_CHANNELS},
        "optional_disabled_by_channel": {channel: 0 for channel in DOCUMENT_INDEX_CHANNELS},
        "optional_skipped_by_channel": {channel: 0 for channel in DOCUMENT_INDEX_CHANNELS},
    }


def _document_index_channel_statuses(
    *,
    document: Any,
    statuses: dict[str, dict[str, Any]] | None,
    has_rows: bool,
) -> dict[str, dict[str, Any]]:
    flags = _document_channel_flags(document)
    resolved = dict(statuses or {})
    for channel in DOCUMENT_INDEX_CHANNELS:
        resolved.setdefault(
            channel,
            _legacy_index_channel_status(document, channel=channel, enabled=bool(flags.get(channel, False))),
        )
    if not has_rows:
        return resolved
    return resolved


def _positive_channel_counts(values: dict[str, int]) -> dict[str, int]:
    return {channel: int(count) for channel, count in values.items() if int(count or 0) > 0}


def _accumulate_index_channel_summary(summary: dict[str, Any], *, statuses: dict[str, dict[str, Any]], used_legacy_fallback: bool) -> None:
    doc_required_pending = False
    doc_required_error = False
    doc_optional_disabled = False
    doc_optional_skipped = False
    if used_legacy_fallback:
        summary["documents_using_legacy_fallback"] += 1

    for channel, payload in statuses.items():
        status = str(payload.get("status") or "").strip().lower() or "pending"
        enabled = bool(payload.get("enabled"))
        summary["status_counts"][status] = int(summary["status_counts"].get(status, 0) or 0) + 1
        channel_status_counts = summary["status_counts_by_channel"].setdefault(channel, {})
        channel_status_counts[status] = int(channel_status_counts.get(status, 0) or 0) + 1
        if bool(payload.get("legacy")):
            summary["legacy_by_channel"][channel] = int(summary["legacy_by_channel"].get(channel, 0) or 0) + 1
        if enabled and status in DOCUMENT_INDEX_CHANNEL_TERMINAL_ERROR:
            summary["required_error_by_channel"][channel] = int(summary["required_error_by_channel"].get(channel, 0) or 0) + 1
            doc_required_error = True
            continue
        if enabled and status not in DOCUMENT_INDEX_CHANNEL_TERMINAL_READY | DOCUMENT_INDEX_CHANNEL_TERMINAL_ERROR:
            summary["required_pending_by_channel"][channel] = int(summary["required_pending_by_channel"].get(channel, 0) or 0) + 1
            doc_required_pending = True
            continue
        if not enabled and status == "disabled":
            summary["optional_disabled_by_channel"][channel] = int(summary["optional_disabled_by_channel"].get(channel, 0) or 0) + 1
            doc_optional_disabled = True
            continue
        if not enabled and status == "skipped":
            summary["optional_skipped_by_channel"][channel] = int(summary["optional_skipped_by_channel"].get(channel, 0) or 0) + 1
            doc_optional_skipped = True

    summary["required_error_documents"] += int(doc_required_error)
    summary["required_pending_documents"] += int(doc_required_pending)
    summary["optional_disabled_documents"] += int(doc_optional_disabled)
    summary["optional_skipped_documents"] += int(doc_optional_skipped)
    if not doc_required_pending and not doc_required_error:
        summary["ready_documents"] += 1


def _finalize_index_channel_audit_summary(summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "documents_with_channel_rows": int(summary["documents_with_channel_rows"]),
        "documents_using_legacy_fallback": int(summary["documents_using_legacy_fallback"]),
        "ready_documents": int(summary["ready_documents"]),
        "required_pending_documents": int(summary["required_pending_documents"]),
        "required_error_documents": int(summary["required_error_documents"]),
        "optional_disabled_documents": int(summary["optional_disabled_documents"]),
        "optional_skipped_documents": int(summary["optional_skipped_documents"]),
        "required_pending_channels": int(sum(summary["required_pending_by_channel"].values())),
        "required_error_channels": int(sum(summary["required_error_by_channel"].values())),
        "optional_disabled_channels": int(sum(summary["optional_disabled_by_channel"].values())),
        "optional_skipped_channels": int(sum(summary["optional_skipped_by_channel"].values())),
        "required_pending_by_channel": _positive_channel_counts(summary["required_pending_by_channel"]),
        "required_error_by_channel": _positive_channel_counts(summary["required_error_by_channel"]),
        "optional_disabled_by_channel": _positive_channel_counts(summary["optional_disabled_by_channel"]),
        "optional_skipped_by_channel": _positive_channel_counts(summary["optional_skipped_by_channel"]),
        "status_counts": dict(sorted(summary["status_counts"].items(), key=lambda item: item[0])),
        "status_counts_by_channel": {
            channel: dict(sorted(counts.items(), key=lambda item: item[0]))
            for channel, counts in summary["status_counts_by_channel"].items()
            if counts
        },
        "legacy_by_channel": _positive_channel_counts(summary["legacy_by_channel"]),
    }


def compute_index_channel_audit_summary(
    *,
    documents: list[Any],
    channel_rows: list[Any],
) -> dict[str, Any]:
    rows_by_document, rows_seen_by_document = _index_channel_rows_by_document(documents=documents, channel_rows=channel_rows)
    summary = _empty_index_channel_audit_summary()
    summary["documents_with_channel_rows"] = int(len(rows_seen_by_document))
    for document in documents:
        document_key = str(getattr(document, "id", "") or "")
        _accumulate_index_channel_summary(
            summary,
            statuses=_document_index_channel_statuses(
                document=document,
                statuses=rows_by_document.get(document_key),
                has_rows=document_key in rows_seen_by_document,
            ),
            used_legacy_fallback=document_key not in rows_seen_by_document,
        )
    return _finalize_index_channel_audit_summary(summary)


def get_index_audit_reconcile_document_state(
    *,
    db: Session,
    tenant_id: UUID,
    dataset_id: UUID,
    document_id: UUID,
) -> dict[str, Any] | None:
    DatasetService.get_dataset(db, tenant_id, dataset_id)
    document = (
        db.query(DBDocument)
        .filter(
            DBDocument.tenant_id == tenant_id,
            DBDocument.dataset_id == dataset_id,
            DBDocument.id == document_id,
        )
        .first()
    )
    if document is None:
        return None
    summary = summarize_document_index_channels(db, document=document).to_dict()
    return {
        "document": document,
        "current_index_readiness": summary,
        "already_ready": bool(summary.get("ready")),
    }


def _bounded_index_audit_reconcile_scan_limit(limit: int | None) -> int:
    try:
        parsed = int(limit or 0)
    except (TypeError, ValueError):
        parsed = 0
    if parsed <= 0:
        parsed = _DEFAULT_INDEX_AUDIT_RECONCILE_SCAN_LIMIT
    return max(1, min(parsed, _MAX_INDEX_AUDIT_RECONCILE_SCAN_LIMIT))


def _active_index_audit_documents_query(
    *,
    db: Session,
    tenant_id: UUID,
    dataset_id: UUID,
):
    doc_ready_clause = or_(
        DBDocument.status == "completed",
        (DBDocument.doc_metadata["active_pipeline_ready"].astext == "true"),  # type: ignore[attr-defined]
    )
    return (
        db.query(DBDocument)
        .filter(
            DBDocument.tenant_id == tenant_id,
            DBDocument.dataset_id == dataset_id,
            DBDocument.archived_at.is_(None),
            DBDocument.disabled_at.is_(None),
        )
        .filter(doc_ready_clause)
        .order_by(DBDocument.updated_at.desc().nullslast(), DBDocument.id.desc())  # type: ignore[attr-defined]
    )


def _build_index_audit_reconcile_document_status_payload(
    *,
    db: Session,
    tenant_id: UUID,
    dataset_id: UUID,
    document: DBDocument,
) -> dict[str, Any]:
    summary = summarize_document_index_channels(db, document=document).to_dict()
    pipeline_hash = _document_pipeline_hash(document)
    rows_query = db.query(DocumentIndexChannel).filter(
        DocumentIndexChannel.tenant_id == tenant_id,
        DocumentIndexChannel.document_id == document.id,
    )
    if pipeline_hash:
        rows_query = rows_query.filter(DocumentIndexChannel.pipeline_hash == pipeline_hash)
    channel_rows_present = len(list(rows_query.all()))
    classified = _classify_index_audit_reconcile_status(
        current_index_readiness=summary,
        channel_rows_present=channel_rows_present,
    )
    return {
        "schema": "mimirq.index_audit_reconcile_status.v1",
        "tenant_id": str(tenant_id),
        "dataset_id": str(dataset_id),
        "document_id": str(document.id),
        "status": classified["status"],
        "reason": classified["reason"],
        "legacy": bool(classified["legacy"]),
        "ready": bool(classified["ready"]),
        "channel_rows_present": int(classified["channel_rows_present"]),
        "current_index_readiness": summary,
    }


def _classify_index_audit_reconcile_status(
    *,
    current_index_readiness: dict[str, Any],
    channel_rows_present: int,
) -> dict[str, Any]:
    summary = dict(current_index_readiness or {})
    pending_channels = list(summary.get("pending_channels") or [])
    error_channels = list(summary.get("error_channels") or [])
    ready = bool(summary.get("ready"))
    rows_present = max(0, int(channel_rows_present or 0))

    if rows_present <= 0:
        status = "legacy_unknown"
        reason = "document_has_no_current_pipeline_channel_rows"
    elif error_channels:
        status = "error"
        reason = "document_index_channels_error"
    elif pending_channels:
        status = "pending"
        reason = "document_index_channels_pending"
    elif ready:
        status = "ready"
        reason = None
    else:
        status = "unknown"
        reason = "document_index_channels_unknown"

    return {
        "status": status,
        "reason": reason,
        "legacy": bool(rows_present <= 0),
        "channel_rows_present": rows_present,
        "ready": ready,
    }


def get_index_audit_reconcile_document_status(
    *,
    db: Session,
    tenant_id: UUID,
    dataset_id: UUID,
    document_id: UUID,
) -> dict[str, Any] | None:
    state = get_index_audit_reconcile_document_state(
        db=db,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        document_id=document_id,
    )
    if state is None:
        return None
    document = state.get("document")
    if document is None:
        return None
    return _build_index_audit_reconcile_document_status_payload(
        db=db,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        document=document,
    )


def plan_index_audit_reconcile(
    *,
    db: Session,
    tenant_id: UUID,
    dataset_id: UUID,
    document_id: UUID | None = None,
    limit: int | None = None,
    dry_run: bool = True,
) -> dict[str, Any]:
    DatasetService.get_dataset(db, tenant_id, dataset_id)
    cap = _bounded_index_audit_reconcile_scan_limit(limit)

    documents: list[DBDocument]
    if document_id is not None:
        document = (
            db.query(DBDocument)
            .filter(
                DBDocument.tenant_id == tenant_id,
                DBDocument.dataset_id == dataset_id,
                DBDocument.id == document_id,
            )
            .first()
        )
        documents = [document] if document is not None else []
    else:
        documents = list(_active_index_audit_documents_query(db=db, tenant_id=tenant_id, dataset_id=dataset_id).limit(cap).all())

    items: list[dict[str, Any]] = []
    counts = {
        "ready": 0,
        "pending": 0,
        "error": 0,
        "legacy_unknown": 0,
        "unknown": 0,
        "candidate_documents": 0,
        "report_only_documents": 0,
    }
    for document in documents:
        status_payload = _build_index_audit_reconcile_document_status_payload(
            db=db,
            tenant_id=tenant_id,
            dataset_id=dataset_id,
            document=document,
        )
        status = str(status_payload.get("status") or "unknown")
        counts[status] = int(counts.get(status, 0) or 0) + 1
        action = "enqueue_rebuild" if status in {"pending", "error"} else "report_only"
        if action == "enqueue_rebuild":
            counts["candidate_documents"] = int(counts["candidate_documents"] or 0) + 1
        else:
            counts["report_only_documents"] = int(counts["report_only_documents"] or 0) + 1
        items.append(
            {
                "document_id": str(document.id),
                "status": status,
                "reason": status_payload.get("reason"),
                "legacy": bool(status_payload.get("legacy")),
                "ready": bool(status_payload.get("ready")),
                "channel_rows_present": int(status_payload.get("channel_rows_present") or 0),
                "action": action,
                "current_index_readiness": dict(status_payload.get("current_index_readiness") or {}),
            }
        )

    return {
        "schema": "mimirq.index_audit_reconcile_plan.v1",
        "tenant_id": str(tenant_id),
        "dataset_id": str(dataset_id),
        "document_id": str(document_id) if document_id is not None else None,
        "scope": ("document" if document_id is not None else "dataset"),
        "dry_run": bool(dry_run),
        "scan_limit": int(cap),
        "scanned_documents": int(len(documents)),
        "counts": counts,
        "items": items,
    }


async def enqueue_index_audit_reconcile(
    *,
    tenant_id: UUID,
    dataset_id: UUID,
    document_id: UUID | None,
    requested_by: str,
) -> dict[str, Any]:
    if document_id is None:
        return {
            "schema": "mimirq.index_audit_reconcile.v1",
            "tenant_id": str(tenant_id),
            "dataset_id": str(dataset_id),
            "document_id": None,
            "scope": "dataset",
            "status": "unsupported",
            "reason": "dataset_scoped_reconcile_not_supported_by_current_worker",
            "task_id": None,
        }
    if not bool(getattr(settings, "TASK_QUEUE_ENABLED", False)):
        return {
            "schema": "mimirq.index_audit_reconcile.v1",
            "tenant_id": str(tenant_id),
            "dataset_id": str(dataset_id),
            "document_id": str(document_id),
            "scope": "document",
            "status": "not_enqueued",
            "reason": "task_queue_disabled",
            "task_id": None,
        }

    from app.tasks.queue import enqueue_rebuild_indexes

    task_id = await enqueue_rebuild_indexes(
        tenant_id=tenant_id,
        document_id=document_id,
        requested_by=str(requested_by or "system:index-audit"),
        job_id=f"index-audit-reconcile:{tenant_id}:{dataset_id}:{document_id}",
    )
    return {
        "schema": "mimirq.index_audit_reconcile.v1",
        "tenant_id": str(tenant_id),
        "dataset_id": str(dataset_id),
        "document_id": str(document_id),
        "scope": "document",
        "status": ("enqueued" if task_id else "already_queued"),
        "reason": (None if task_id else "duplicate_job"),
        "task_id": str(task_id) if task_id else None,
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


def _active_index_audit_documents(db: Session, *, tenant_id: UUID, dataset_id: UUID, doc_ready_clause: Any) -> tuple[list[Any], list[UUID]]:
    docs_q = (
        db.query(DBDocument)
        .filter(
            DBDocument.tenant_id == tenant_id,
            DBDocument.dataset_id == dataset_id,
            DBDocument.archived_at.is_(None),
            DBDocument.disabled_at.is_(None),
        )
        .filter(doc_ready_clause)
    )
    active_documents_rows = [row for row in docs_q.all() if row and getattr(row, "id", None)]
    return active_documents_rows, [row.id for row in active_documents_rows]


def _milvus_existing_vector_ids(vector_ids_checked: list[str]) -> set[str] | None:
    if not vector_ids_checked:
        return None
    try:
        from app.storage.vector.milvus import milvus_store

        return milvus_store.fetch_existing_ids(vector_ids_checked)
    except Exception:
        return None


def _milvus_ids_sample(*, tenant_id: UUID, dataset_id: UUID, milvus_list_limit: int) -> list[str] | None:
    if int(milvus_list_limit or 0) <= 0:
        return None
    try:
        from app.storage.vector.milvus import milvus_store

        return milvus_store.list_ids_by_dataset(
            tenant_id=tenant_id,
            dataset_id=dataset_id,
            limit=max(0, int(milvus_list_limit or 0)),
            offset=0,
        )
    except Exception:
        return None


def _active_chunk_ids_present(chunks_q: Any, milvus_ids_sample: list[str] | None) -> set[str] | None:
    if not milvus_ids_sample:
        return None
    want: list[UUID] = []
    for raw in milvus_ids_sample:
        try:
            want.append(UUID(str(raw)))
        except Exception:
            get_logger(__name__).debug("Skipping item after non-critical exception", exc_info=True)
    if not want:
        return set()
    rows = chunks_q.filter(DocumentChunk.id.in_(want)).with_entities(DocumentChunk.id).all()
    return {str(row[0]) for row in rows if row and row[0]}


def _dataset_index_channel_summary(
    db: Session,
    *,
    tenant_id: UUID,
    dataset_id: UUID,
    active_doc_ids: list[UUID],
    active_documents_rows: list[Any],
) -> dict[str, Any]:
    if not active_doc_ids:
        return {}
    channel_rows = list(
        db.query(DocumentIndexChannel)
        .filter(
            DocumentIndexChannel.tenant_id == tenant_id,
            DocumentIndexChannel.dataset_id == dataset_id,
            DocumentIndexChannel.document_id.in_(active_doc_ids),
        )
        .all()
    )
    return compute_index_channel_audit_summary(documents=active_documents_rows, channel_rows=channel_rows)


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
    active_documents_rows, active_doc_ids = _active_index_audit_documents(
        db,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        doc_ready_clause=doc_ready_clause,
    )
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

    vector_backend = str(getattr(settings, "VECTOR_BACKEND", "milvus") or "milvus").strip().lower()
    vector_ids_existing = _milvus_existing_vector_ids(vector_ids_checked) if vector_backend == "milvus" else None
    milvus_ids_sample = _milvus_ids_sample(tenant_id=tenant_id, dataset_id=dataset_id, milvus_list_limit=milvus_list_limit) if vector_backend == "milvus" else None
    active_chunk_ids_present = _active_chunk_ids_present(chunks_q, milvus_ids_sample)
    index_channels = _dataset_index_channel_summary(
        db,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        active_doc_ids=active_doc_ids,
        active_documents_rows=active_documents_rows,
    )

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
        index_channels=index_channels,
        sample_limit=sample_limit,
    )


__all__ = [
    "build_index_drift_marker",
    "compute_index_channel_audit_summary",
    "compute_index_audit_summary",
    "enqueue_index_audit_reconcile",
    "get_index_audit_reconcile_document_status",
    "get_index_audit_reconcile_document_state",
    "list_index_drift_items",
    "plan_index_audit_reconcile",
    "record_index_drift_item",
    "replay_index_drift_items",
    "resolve_index_drift_item",
    "run_dataset_index_audit",
    "run_dataset_index_audit_internal",
]

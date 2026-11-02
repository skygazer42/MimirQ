"""Dify kg on demand operations."""

import contextlib
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.document import Document, DocumentChunk
from app.rag.core.logging import get_logger
from app.services.dify_integration import citation_records, common
from app.services.dify_integration import records as record_values
from app.services.rag_runtime_limiter import run_blocking_retrieval_call
from app.types.dify_integration import DifyKGFlags as _DifyKGFlags

logger = get_logger(__name__)


def _load_dify_kg_chunk_rows(
    *,
    db: Session,
    tenant_id: UUID,
    dataset_ids: list[UUID],
    chunk_ids: list[UUID],
) -> list[Any]:
    return (
        db.query(
            DocumentChunk.id.label("chunk_id"),
            DocumentChunk.document_id.label("document_id"),
            DocumentChunk.chunk_index.label("chunk_index"),
            DocumentChunk.page_number.label("page_number"),
            DocumentChunk.content.label("content"),
            DocumentChunk.doc_metadata.label("metadata"),
            Document.dataset_id.label("dataset_id"),
            Document.filename.label("filename"),
        )
        .join(Document, DocumentChunk.document_id == Document.id)
        .filter(
            DocumentChunk.tenant_id == tenant_id,
            DocumentChunk.id.in_(chunk_ids),
            DocumentChunk.disabled_at.is_(None),
            Document.tenant_id == tenant_id,
            Document.dataset_id.in_(dataset_ids),
            Document.disabled_at.is_(None),
        )
        .all()
    )


def _load_dify_kg_chunk_rows_with_managed_session(
    *,
    tenant_id: UUID,
    dataset_ids: list[UUID],
    chunk_ids: list[UUID],
) -> list[Any]:
    worker_db = SessionLocal()
    try:
        return _load_dify_kg_chunk_rows(
            db=worker_db,
            tenant_id=tenant_id,
            dataset_ids=dataset_ids,
            chunk_ids=chunk_ids,
        )
    finally:
        worker_db.close()


async def _offload_dify_kg_chunk_rows(
    *,
    request_db: Session,
    tenant_id: UUID,
    dataset_ids: list[UUID],
    chunk_ids: list[UUID],
) -> list[Any]:
    rollback = getattr(request_db, "rollback", None)
    if callable(rollback):
        with contextlib.suppress(Exception):
            rollback()
    return await run_blocking_retrieval_call(
        _load_dify_kg_chunk_rows_with_managed_session,
        tenant_id=tenant_id,
        dataset_ids=dataset_ids,
        chunk_ids=chunk_ids,
    )


async def _dify_kg_on_demand_records(
    *,
    db: Session,
    tenant_id: UUID,
    account_id: str,
    dataset_ids: list[UUID],
    query: str,
    requested_kg_flags: _DifyKGFlags,
    policy_plugin_refs: tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    scoped_dataset_ids = _dify_kg_on_demand_dataset_ids(
        dataset_ids,
        requested_kg_flags=requested_kg_flags,
    )
    if not scoped_dataset_ids:
        return []

    try:
        from app.rag.kg.pipeline import kg_search

        kg_result = await kg_search(
            query=query,
            tenant_id=tenant_id,
            dataset_ids=scoped_dataset_ids,
            account_id=account_id,
        )
    except Exception:
        logger.debug("Dify KG on-demand search failed", exc_info=True)
        return []

    events = kg_result.get("events") if isinstance(kg_result, dict) else []
    events = events if isinstance(events, list) else []
    if not events:
        return []

    chunk_events = _dify_kg_chunk_events(
        events,
        max_records=_dify_kg_on_demand_max_records(requested_kg_flags),
    )
    if not chunk_events:
        return []

    event_by_chunk_id = dict(chunk_events)
    try:
        rows = await _offload_dify_kg_chunk_rows(
            request_db=db,
            tenant_id=tenant_id,
            dataset_ids=scoped_dataset_ids,
            chunk_ids=list(event_by_chunk_id),
        )
    except Exception:
        logger.debug("Dify KG on-demand chunk hydration failed", exc_info=True)
        return []

    return _dify_kg_records_from_rows(
        rows,
        chunk_events=chunk_events,
        query=query,
        policy_plugin_refs=policy_plugin_refs,
    )


def _dify_kg_on_demand_dataset_ids(
    dataset_ids: list[UUID],
    *,
    requested_kg_flags: _DifyKGFlags,
) -> list[UUID]:
    if not requested_kg_flags.enabled:
        return []
    if not (settings.KG_ENABLED and settings.KG_CHAT_ENABLED):
        return []
    return common._dedupe_dataset_ids(list(dataset_ids or []))


def _dify_kg_on_demand_max_records(requested_kg_flags: _DifyKGFlags) -> int:
    return max(
        int(requested_kg_flags.chunk_injection_max_chunks if requested_kg_flags.enable_chunk_injection else 0),
        int(requested_kg_flags.chunk_boost_max_promoted if requested_kg_flags.enable_chunk_boost else 0),
        1,
    )


def _dify_kg_chunk_events(
    events: list[Any],
    *,
    max_records: int,
) -> list[tuple[UUID, dict[str, Any]]]:
    chunk_events: list[tuple[UUID, dict[str, Any]]] = []
    seen_chunk_ids: set[UUID] = set()
    for event in events:
        if not isinstance(event, dict):
            continue
        raw_chunk_id = str(event.get("chunk_id") or "").strip()
        if not raw_chunk_id:
            continue
        try:
            chunk_id = UUID(raw_chunk_id)
        except ValueError:
            continue
        if chunk_id in seen_chunk_ids:
            continue
        seen_chunk_ids.add(chunk_id)
        chunk_events.append((chunk_id, event))
        if len(chunk_events) >= max_records:
            break
    return chunk_events


def _dify_kg_record_citation(
    row: Any,
    *,
    chunk_id: UUID,
    event: dict[str, Any],
) -> tuple[dict[str, Any], UUID | None]:
    metadata = record_values._row_value(row, "metadata") or {}
    metadata = dict(metadata) if isinstance(metadata, dict) else {}
    metadata.update(
        {
            "kg_on_demand": True,
            "kg_event_id": str(event.get("id") or event.get("event_id") or ""),
            "kg_score": common._clamp_score(event.get("score") or event.get("weight") or event.get("relevance_score")),
            "chunk_id": str(chunk_id),
            "document_id": str(record_values._row_value(row, "document_id") or ""),
            "chunk_index": record_values._row_value(row, "chunk_index"),
            "page_number": record_values._row_value(row, "page_number"),
        }
    )
    return (
        {
            "content": str(record_values._row_value(row, "content") or ""),
            "relevance_score": metadata["kg_score"],
            "document_name": str(record_values._row_value(row, "filename") or "kg-on-demand"),
            "chunk_id": str(chunk_id),
            "dataset_id": str(record_values._row_value(row, "dataset_id") or ""),
            "metadata": metadata,
        },
        record_values._row_value(row, "dataset_id"),
    )


def _dify_kg_records_from_rows(
    rows: list[Any],
    *,
    chunk_events: list[tuple[UUID, dict[str, Any]]],
    query: str,
    policy_plugin_refs: tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    row_by_chunk_id = {record_values._row_value(row, "chunk_id"): row for row in rows}
    records: list[dict[str, Any]] = []
    for chunk_id, event in chunk_events:
        row = row_by_chunk_id.get(chunk_id)
        if row is None:
            continue
        citation, dataset_id = _dify_kg_record_citation(row, chunk_id=chunk_id, event=event)
        record = citation_records._citation_to_dify_record(
            citation,
            dataset_id=dataset_id,
            query=query,
            policy_plugin_refs=policy_plugin_refs,
        )
        if str(record.get("content") or "").strip():
            records.append(record)
    return records

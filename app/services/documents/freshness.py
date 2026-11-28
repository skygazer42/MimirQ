"""Read tenant-scoped document timestamps for retrieval freshness scoring."""

import logging
from typing import Any
from uuid import UUID

logger = logging.getLogger("app.rag.core.temporal")


def _normalize_document_uuid_list(document_ids: list[str], *, max_docs: int) -> list[UUID]:
    doc_uuid_list: list[UUID] = []
    seen: set[str] = set()
    for raw_document_id in document_ids:
        document_id = raw_document_id.strip()
        if not document_id or document_id in seen:
            continue
        seen.add(document_id)
        try:
            doc_uuid = UUID(document_id)
        except ValueError:
            logger.debug("Skipping malformed document UUID for freshness scoring")
            continue
        doc_uuid_list.append(doc_uuid)
        if len(doc_uuid_list) >= max_docs:
            break
    return doc_uuid_list


def _rows_to_updated_timestamps(rows: list[tuple[Any, Any, Any]]) -> dict[str, float]:
    out: dict[str, float] = {}
    for did, updated_at, created_at in rows:
        ts = updated_at if updated_at is not None else created_at
        if ts is None:
            continue
        out[str(did)] = float(ts.timestamp())
    return out


def _query_document_timestamp_rows(
    *,
    tenant_uuid: UUID,
    dataset_uuid: UUID | None,
    doc_uuid_list: list[UUID],
) -> list[tuple[Any, Any, Any]]:
    from app.infrastructure.database.connection import SessionLocal  # noqa: WPS433
    from app.models.documents.records import Document as DBDocument  # noqa: WPS433

    db = SessionLocal()
    try:
        q = (
            db.query(DBDocument.id, DBDocument.updated_at, DBDocument.created_at)
            .filter(DBDocument.tenant_id == tenant_uuid)
            .filter(DBDocument.id.in_(sorted(doc_uuid_list)))
        )
        if dataset_uuid is not None:
            q = q.filter(DBDocument.dataset_id == dataset_uuid)
        return q.all()
    finally:
        try:
            db.close()
        except Exception as exc:
            logger.debug("Ignoring temporal metadata session close failure: %s", exc)


def fetch_document_updated_ts(
    document_ids: list[str],
    *,
    tenant_id: Any,
    dataset_id: Any | None = None,
    max_docs: int = 200,
) -> dict[str, float]:
    """
    Query DB for document updated timestamps.

    Returns:
      { "<document_uuid>": <ts_seconds> }
    """
    max_docs = max(0, int(max_docs or 0))
    if max_docs <= 0:
        return {}

    if tenant_id is None or not document_ids:
        return {}

    tenant_uuid = tenant_id if isinstance(tenant_id, UUID) else UUID(str(tenant_id))
    dataset_uuid = None
    if dataset_id is not None:
        dataset_uuid = dataset_id if isinstance(dataset_id, UUID) else UUID(str(dataset_id))

    # Parse IDs early to avoid wasting DB calls.
    doc_uuid_list = _normalize_document_uuid_list(document_ids, max_docs=max_docs)
    if not doc_uuid_list:
        return {}

    rows = _query_document_timestamp_rows(
        tenant_uuid=tenant_uuid,
        dataset_uuid=dataset_uuid,
        doc_uuid_list=doc_uuid_list,
    )
    return _rows_to_updated_timestamps(rows)


__all__ = ["fetch_document_updated_ts"]

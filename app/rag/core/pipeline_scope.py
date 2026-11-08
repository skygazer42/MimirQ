"""Active document pipeline filtering shared by graph and streaming retrieval."""

from typing import Any
from uuid import UUID


def _active_pipeline_hash(*, status: Any, meta: Any) -> str | None:
    metadata = {} if meta is None else meta
    ready = (
        bool(metadata.get("active_pipeline_ready"))
        if "active_pipeline_ready" in metadata
        else (str(status or "").lower() == "completed")
    )
    if not ready:
        return None
    from app.core.pipeline_versions import get_active_pipeline_hash

    return get_active_pipeline_hash(metadata)


def apply_active_pipeline_metadata_filter(
    *,
    db: Any,
    tenant_id: UUID | None,
    document_ids: list[UUID] | None,
    metadata_filter: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if db is None or tenant_id is None or not document_ids:
        return metadata_filter
    from app.models.document import Document as DBDocument

    rows = (
        db.query(DBDocument.id, DBDocument.status, DBDocument.doc_metadata)
        .filter(DBDocument.tenant_id == tenant_id, DBDocument.id.in_(list(document_ids)))
        .all()
    )
    active_keys = [
        f"{did}:{active_hash}"
        for did, status, meta in rows
        if (active_hash := _active_pipeline_hash(status=status, meta=meta))
    ]
    if not active_keys:
        return metadata_filter
    scoped_filter = dict(metadata_filter or {})
    scoped_filter["doc_pipeline_key"] = {"$in": set(active_keys)}
    return scoped_filter

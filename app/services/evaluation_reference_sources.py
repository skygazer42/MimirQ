"""Validate regression evidence references against dataset scope and document access."""

from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.constants import NON_CRITICAL_EXCEPTION_LOG_MESSAGE
from app.rag.core.logging import get_logger


def _enrich_reference_source_payload(
    src: dict,
    *,
    chunk_index: int | None,
    chunk_meta: dict | None,
    chunk_content: str | None,
) -> dict:
    """
    Best-effort enrichment for reference_sources payloads.

    Motivation:
    - Regression suites should survive re-ingestion/re-chunking as much as possible.
    - We store `reference_sources` as JSON, so we can enrich without migrations.

    Rules:
    - Never override explicitly provided fields.
    - Fill missing `quote` from chunk content (bounded).
    - Fill missing versioning fields (`doc_pipeline_key`, `pipeline_hash`) from chunk metadata.
    - Fill missing `chunk_index` from DB column.
    """
    payload = dict(src)

    if chunk_index is not None and payload.get("chunk_index") is None:
        payload["chunk_index"] = chunk_index

    meta = chunk_meta if isinstance(chunk_meta, dict) else {}
    if "doc_pipeline_key" not in payload:
        v = meta.get("doc_pipeline_key")
        if isinstance(v, str) and v.strip():
            payload["doc_pipeline_key"] = v.strip()
    if "pipeline_hash" not in payload:
        v = meta.get("pipeline_hash")
        if isinstance(v, str) and v.strip():
            payload["pipeline_hash"] = v.strip()

    if "quote" not in payload and chunk_content is not None:
        text = chunk_content.strip()
        if text:
            payload["quote"] = text[:2000] + ("..." if len(text) > 2000 else "")

    return payload


def finalize_reference_sources(
    db: Session,
    *,
    tenant_id: UUID,
    account_id: str,
    dataset_id: UUID,
    reference_sources: list[dict] | list[Any],
) -> list[dict]:
    """
    Validate and normalize reference_sources payload for DB storage.

    Security:
    - Enforces tenant isolation and document ACL checks.
    Consistency:
    - Ensures (chunk_id -> document_id -> dataset_id) matches.
    UX:
    - Best-effort fill `quote` from chunk content when missing.
    """
    # Import lazily to keep module import side-effects minimal.
    from app.models.document import Document as DBDocument
    from app.models.document import DocumentChunk
    from app.services.document_access import filter_allowed_document_ids

    coerced = _coerce_reference_sources(reference_sources)
    doc_ids, chunk_ids = _reference_source_ids(coerced)

    # ACL: all evidence documents must be readable.
    allowed_docs = set(filter_allowed_document_ids(db, tenant_id, account_id, doc_ids))
    if set(doc_ids) - allowed_docs:
        raise HTTPException(status_code=403, detail="Evidence documents not accessible")

    # Validate chunk ownership + dataset match; pull content for quote fallback.
    rows = (
        db.query(
            DocumentChunk.id,
            DocumentChunk.document_id,
            DBDocument.dataset_id,
            DocumentChunk.content,
            DocumentChunk.disabled_at,
            DocumentChunk.chunk_index,
            DocumentChunk.doc_metadata,
        )
        .join(DBDocument, DBDocument.id == DocumentChunk.document_id)
        .filter(
            DocumentChunk.tenant_id == tenant_id,
            DocumentChunk.id.in_(chunk_ids),
            DBDocument.tenant_id == tenant_id,
        )
        .all()
    )
    row_by_chunk_id = {row[0]: row for row in rows}
    if len(row_by_chunk_id) < len(set(chunk_ids)):
        raise HTTPException(status_code=400, detail="Some evidence chunks were not found")

    out: list[dict] = []
    for source in coerced:
        payload = _validated_reference_source_payload(source, row_by_chunk_id, dataset_id)
        if payload is not None:
            out.append(payload)

    if not out:
        raise HTTPException(status_code=400, detail="reference_sources is empty or invalid")

    return out


def _coerce_reference_sources(reference_sources: list[dict] | list[Any]) -> list[dict]:
    """Convert supported reference-source objects into independent dictionaries."""
    coerced: list[dict] = []
    for source in reference_sources:
        if source is None:
            continue
        if hasattr(source, "model_dump"):
            coerced.append(source.model_dump(mode="json"))
        elif isinstance(source, dict):
            coerced.append(dict(source))
    return coerced


def _reference_source_ids(reference_sources: list[dict]) -> tuple[list[UUID], list[UUID]]:
    """Collect valid document and chunk identifiers with the original skip semantics."""
    document_ids: list[UUID] = []
    chunk_ids: list[UUID] = []
    for source in reference_sources:
        try:
            document_ids.append(UUID(str(source.get("document_id"))))
        except ValueError:
            get_logger(__name__).debug(NON_CRITICAL_EXCEPTION_LOG_MESSAGE, exc_info=True)
            continue
        try:
            chunk_ids.append(UUID(str(source.get("chunk_id"))))
        except ValueError:
            get_logger(__name__).debug(NON_CRITICAL_EXCEPTION_LOG_MESSAGE, exc_info=True)
    return document_ids, chunk_ids


def _validated_reference_source_payload(
    source: dict,
    row_by_chunk_id: dict[UUID, Any],
    dataset_id: UUID,
) -> dict | None:
    chunk_id_raw = source.get("chunk_id")
    document_id_raw = source.get("document_id")
    if not chunk_id_raw or not document_id_raw:
        return None
    try:
        chunk_id = UUID(str(chunk_id_raw))
        document_id = UUID(str(document_id_raw))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid evidence chunk_id/document_id") from exc

    row = row_by_chunk_id.get(chunk_id)
    if row is None:
        raise HTTPException(status_code=400, detail="Evidence chunk not found")
    _chunk_id, chunk_document_id, chunk_dataset_id, content, disabled_at, chunk_index, chunk_meta = row
    if disabled_at is not None:
        raise HTTPException(status_code=400, detail="Evidence chunk is disabled")
    if chunk_document_id != document_id:
        raise HTTPException(status_code=400, detail="Evidence chunk does not belong to document_id")
    if chunk_dataset_id != dataset_id:
        raise HTTPException(status_code=400, detail="Evidence chunk does not belong to dataset_id")

    return _enrich_reference_source_payload(
        source,
        chunk_index=chunk_index if isinstance(chunk_index, int) else None,
        chunk_meta=(chunk_meta if isinstance(chunk_meta, dict) else None),
        chunk_content=(content if isinstance(content, str) else None),
    )

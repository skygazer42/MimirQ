"""Dify chunk hydration rules and operations."""

from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.document import DocumentChunk
from app.rag.core.logging import get_logger
from app.services.dify_integration.common import _citation_chunk_id as _citation_chunk_id
from app.services.rag_runtime_limiter import run_blocking_retrieval_call

logger = get_logger(__name__)


def _load_chunk_content_map(
    *,
    db: Session,
    tenant_id: UUID,
    citations: list[dict[str, Any]],
) -> dict[str, str]:
    chunk_ids: list[UUID] = []
    seen: set[UUID] = set()
    for citation in citations or []:
        chunk_id = _citation_chunk_id(citation)
        if not chunk_id:
            continue
        try:
            parsed = UUID(chunk_id)
        except ValueError:
            continue
        if parsed in seen:
            continue
        seen.add(parsed)
        chunk_ids.append(parsed)
    if not chunk_ids:
        return {}

    try:
        rows = (
            db.query(DocumentChunk.id, DocumentChunk.content)
            .filter(
                DocumentChunk.tenant_id == tenant_id,
                DocumentChunk.id.in_(chunk_ids),
                DocumentChunk.disabled_at.is_(None),
            )
            .all()
        )
    except Exception:  # noqa: BLE001
        logger.warning("Failed to hydrate Dify chunk content; falling back to citation snippets", exc_info=True)
        return {}
    out: dict[str, str] = {}
    for chunk_id, content in rows:
        text = content.strip()
        if text:
            out[str(chunk_id)] = text
    return out


def _load_chunk_content_map_with_managed_session(
    *,
    tenant_id: UUID,
    citations: list[dict[str, Any]],
) -> dict[str, str]:
    worker_db = SessionLocal()
    try:
        return _load_chunk_content_map(
            db=worker_db,
            tenant_id=tenant_id,
            citations=citations,
        )
    finally:
        worker_db.close()


async def _offload_chunk_content_hydration(
    *,
    request_db: Session,
    tenant_id: UUID,
    citations: list[dict[str, Any]],
) -> dict[str, str]:
    rollback = getattr(request_db, "rollback", None)
    if callable(rollback):
        rollback()
    return await run_blocking_retrieval_call(
        _load_chunk_content_map_with_managed_session,
        tenant_id=tenant_id,
        citations=citations,
    )

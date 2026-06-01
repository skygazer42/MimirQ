"""
Corpus cache token helpers.

These helpers build bounded invalidation tokens for cache keys that depend on
the currently served corpus version.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.dataset import Dataset
from app.models.document import Document as DBDocument
from app.rag.core.hashing import stable_hash
from app.rag.core.logging import get_logger
from app.rag.rerank_result_cache import clear_evidence_post_rerank_cache

logger = get_logger(__name__)


def _as_iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        try:
            return value.isoformat()
        except Exception:
            return None
    text = str(value or "").strip()
    return text or None


def _active_pipeline_hash(meta: Any) -> str | None:
    payload = meta if isinstance(meta, dict) else {}
    out = str(payload.get("active_pipeline_hash") or payload.get("pipeline_hash") or "").strip()
    return out or None


def build_dataset_scope_corpus_cache_token(*, dataset_id: Any, updated_at: Any) -> str | None:
    ds = str(dataset_id or "").strip()
    if not ds:
        return None
    sig = {
        "schema": "mimirq.dataset_corpus_cache_token.v1",
        "dataset_id": ds,
        "updated_at": _as_iso(updated_at),
    }
    raw = json.dumps(sig, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return stable_hash(raw, length=24)


def build_document_scope_corpus_cache_token(rows: Sequence[Any]) -> str | None:
    items: list[dict[str, Any]] = []
    for row in rows or []:
        payload = row if isinstance(row, dict) else {}
        doc_id = str(payload.get("id") or "").strip()
        if not doc_id:
            continue
        items.append(
            {
                "id": doc_id,
                "updated_at": _as_iso(payload.get("updated_at")),
                "active_pipeline_hash": _active_pipeline_hash(payload),
            }
        )

    if not items:
        return None

    items.sort(key=lambda x: x["id"])
    raw = json.dumps(
        {
            "schema": "mimirq.document_scope_corpus_cache_token.v1",
            "documents": items,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )
    return stable_hash(raw, length=24)


def resolve_corpus_cache_token(
    db: Session,
    *,
    tenant_id: UUID,
    dataset_id: UUID | None = None,
    document_ids: Sequence[UUID] | None = None,
) -> str | None:
    doc_ids = [d for d in (document_ids or []) if d is not None]
    if doc_ids:
        rows = (
            db.query(DBDocument.id, DBDocument.updated_at, DBDocument.doc_metadata)
            .filter(DBDocument.tenant_id == tenant_id, DBDocument.id.in_(list(doc_ids)))
            .all()
        )
        if len(rows) != len(doc_ids):
            return None
        docs: list[dict[str, Any]] = []
        for doc_id, updated_at, doc_meta in rows:
            docs.append(
                {
                    "id": str(doc_id),
                    "updated_at": updated_at,
                    "active_pipeline_hash": _active_pipeline_hash(doc_meta),
                }
            )
        return build_document_scope_corpus_cache_token(docs)

    if dataset_id is not None:
        row = (
            db.query(Dataset.updated_at)
            .filter(Dataset.tenant_id == tenant_id, Dataset.id == dataset_id)
            .first()
        )
        updated_at = row[0] if row else None
        return build_dataset_scope_corpus_cache_token(dataset_id=str(dataset_id), updated_at=updated_at)

    return None


def invalidate_dataset_cache_namespace(
    db: Session,
    *,
    tenant_id: UUID,
    dataset_id: UUID,
) -> dict[str, Any]:
    previous_token = resolve_corpus_cache_token(
        db,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        document_ids=[],
    )

    dataset = (
        db.query(Dataset)
        .filter(Dataset.tenant_id == tenant_id, Dataset.id == dataset_id)
        .first()
    )
    if dataset is None:
        raise LookupError("dataset not found")

    invalidated_at = datetime.now(UTC)
    dataset.updated_at = invalidated_at

    try:
        flush = getattr(db, "flush", None)
        if callable(flush):
            flush()
    except Exception as exc:
        logger.debug("Ignoring corpus cache namespace flush failure: %s", exc)

    current_token = resolve_corpus_cache_token(
        db,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        document_ids=[],
    )
    memory_cleared = bool(clear_evidence_post_rerank_cache())

    return {
        "dataset_id": str(dataset_id),
        "previous_corpus_cache_token": previous_token,
        "current_corpus_cache_token": current_token,
        "invalidated_at": invalidated_at,
        "evidence_post_rerank_memory_cleared": memory_cleared,
        "note": "Dataset caches are invalidated by rotating the dataset corpus token. Existing redis entries expire by TTL.",
    }


__all__ = [
    "build_dataset_scope_corpus_cache_token",
    "build_document_scope_corpus_cache_token",
    "invalidate_dataset_cache_namespace",
    "resolve_corpus_cache_token",
]

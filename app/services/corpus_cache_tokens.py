"""
Corpus cache token helpers.

These helpers build bounded invalidation tokens for cache keys that depend on
the currently served corpus version.
"""

import json
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.pipeline_versions import get_active_pipeline_hash
from app.models.dataset import Dataset
from app.models.document import Document as DBDocument
from app.rag.core.hashing import stable_hash
from app.rag.rerank_result_cache import clear_evidence_post_rerank_cache
from app.services.dataset_embedding_config import resolve_dataset_embedding_runtime


def _as_iso(value: datetime | str | None) -> str | None:
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _dataset_embedding_binding(dataset_meta: Any) -> dict[str, Any]:
    metadata = dict(dataset_meta or {}) if isinstance(dataset_meta, dict) else {}
    runtime = resolve_dataset_embedding_runtime(metadata)
    raw_defaults = metadata.get("embedding_defaults")
    if not isinstance(raw_defaults, dict):
        raw_defaults = {}
    embedding_defaults = {key: raw_defaults.get(key) for key in ("provider", "model", "api_base")}
    return {
        "dataset_scoped": runtime.dataset_scoped,
        "provider": runtime.provider,
        "model": runtime.model,
        "api_base": runtime.api_base,
        "embedding_space_hash": runtime.embedding_space_hash,
        "embedding_defaults": embedding_defaults,
    }


def build_dataset_scope_corpus_cache_token(
    *, dataset_id: Any, updated_at: Any, dataset_embedding_binding: Any = None
) -> str | None:
    ds = str(dataset_id or "").strip()
    if not ds:
        return None
    sig = {
        "schema": "mimirq.dataset_corpus_cache_token.v1",
        "dataset_id": ds,
        "updated_at": _as_iso(updated_at),
        "dataset_embedding_binding": dataset_embedding_binding,
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
                "dataset_id": payload.get("dataset_id"),
                "updated_at": _as_iso(payload.get("updated_at")),
                "active_pipeline_hash": get_active_pipeline_hash(payload),
                "dataset_embedding_binding": payload.get("dataset_embedding_binding"),
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


def build_multi_dataset_scope_corpus_cache_token(rows: Sequence[Any]) -> str | None:
    items: list[dict[str, Any]] = []
    for row in rows or []:
        payload = row if isinstance(row, dict) else {}
        dataset_id = str(payload.get("dataset_id") or payload.get("id") or "").strip()
        if not dataset_id:
            continue
        items.append(
            {
                "dataset_id": dataset_id,
                "updated_at": _as_iso(payload.get("updated_at")),
                "dataset_embedding_binding": payload.get("dataset_embedding_binding"),
            }
        )

    if not items:
        return None

    items.sort(key=lambda item: item["dataset_id"])
    raw = json.dumps(
        {
            "schema": "mimirq.multi_dataset_scope_corpus_cache_token.v1",
            "datasets": items,
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
    dataset_ids: Sequence[UUID] | None = None,
    document_ids: Sequence[UUID] | None = None,
) -> str | None:
    doc_ids = [d for d in (document_ids if document_ids is not None else []) if d is not None]
    if doc_ids:
        rows = (
            db.query(DBDocument.id, DBDocument.dataset_id, DBDocument.updated_at, DBDocument.doc_metadata)
            .filter(DBDocument.tenant_id == tenant_id, DBDocument.id.in_(list(doc_ids)))
            .all()
        )
        if len(rows) != len(doc_ids):
            return None
        dataset_ids = sorted({dataset_id for _, dataset_id, _, _ in rows if dataset_id is not None}, key=str)
        dataset_meta_by_id: dict[str, dict[str, Any]] = {}
        if dataset_ids:
            dataset_rows = (
                db.query(Dataset.id, Dataset.dataset_metadata)
                .filter(Dataset.tenant_id == tenant_id, Dataset.id.in_(dataset_ids))
                .all()
            )
            dataset_meta_by_id = {
                str(scope_dataset_id): dict(dataset_meta or {}) if isinstance(dataset_meta, dict) else {}
                for scope_dataset_id, dataset_meta in dataset_rows
            }
        docs: list[dict[str, Any]] = []
        for doc_id, scope_dataset_id, updated_at, doc_meta in rows:
            docs.append(
                {
                    "id": str(doc_id),
                    "dataset_id": str(scope_dataset_id) if scope_dataset_id is not None else None,
                    "updated_at": updated_at,
                    "active_pipeline_hash": get_active_pipeline_hash(doc_meta if isinstance(doc_meta, dict) else {}),
                    "dataset_embedding_binding": _dataset_embedding_binding(
                        dataset_meta_by_id.get(str(scope_dataset_id))
                    )
                    if scope_dataset_id is not None
                    else None,
                }
            )
        return build_document_scope_corpus_cache_token(docs)

    if dataset_id is not None:
        row = (
            db.query(Dataset.updated_at, Dataset.dataset_metadata)
            .filter(Dataset.tenant_id == tenant_id, Dataset.id == dataset_id)
            .first()
        )
        if row is None:
            return None
        updated_at, dataset_meta = row
        return build_dataset_scope_corpus_cache_token(
            dataset_id=str(dataset_id),
            updated_at=updated_at,
            dataset_embedding_binding=_dataset_embedding_binding(dataset_meta),
        )

    scope_dataset_ids = sorted(
        {
            dataset_scope_id
            for dataset_scope_id in (dataset_ids if dataset_ids is not None else [])
            if dataset_scope_id is not None
        },
        key=str,
    )
    if scope_dataset_ids:
        rows = (
            db.query(Dataset.id, Dataset.updated_at, Dataset.dataset_metadata)
            .filter(Dataset.tenant_id == tenant_id, Dataset.id.in_(scope_dataset_ids))
            .all()
        )
        if len(rows) != len(scope_dataset_ids):
            return None
        datasets: list[dict[str, Any]] = []
        for scope_dataset_id, updated_at, dataset_meta in rows:
            datasets.append(
                {
                    "dataset_id": str(scope_dataset_id),
                    "updated_at": updated_at,
                    "dataset_embedding_binding": _dataset_embedding_binding(dataset_meta),
                }
            )
        return build_multi_dataset_scope_corpus_cache_token(datasets)

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

    dataset = db.query(Dataset).filter(Dataset.tenant_id == tenant_id, Dataset.id == dataset_id).first()
    if dataset is None:
        raise LookupError("dataset not found")

    invalidated_at = datetime.now(UTC)
    dataset.updated_at = invalidated_at

    db.flush()

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
        "note": (
            "Dataset caches are invalidated by rotating the dataset corpus token. Existing redis entries expire by TTL."
        ),
    }


def invalidate_corpus_cache_scope(
    db: Session,
    *,
    tenant_id: UUID,
    dataset_ids: Sequence[UUID] = (),
    document_ids: Sequence[UUID] = (),
) -> None:
    """Rotate existing document/dataset revisions after an index rebuild; caller commits."""
    documents = db.query(DBDocument).filter(DBDocument.tenant_id == tenant_id)
    if dataset_ids:
        documents = documents.filter(DBDocument.dataset_id.in_(list(dataset_ids)))
    if document_ids:
        documents = documents.filter(DBDocument.id.in_(list(document_ids)))
    affected_datasets = set(dataset_ids)
    if document_ids and not dataset_ids:
        affected_datasets.update(
            dataset_id
            for (dataset_id,) in documents.with_entities(DBDocument.dataset_id).distinct()
            if dataset_id is not None
        )
    now = datetime.now(UTC)
    documents.update({DBDocument.updated_at: now}, synchronize_session=False)
    datasets = db.query(Dataset).filter(Dataset.tenant_id == tenant_id)
    if dataset_ids or document_ids:
        datasets = datasets.filter(Dataset.id.in_(list(affected_datasets)))
    datasets.update({Dataset.updated_at: now}, synchronize_session=False)
    db.flush()
    clear_evidence_post_rerank_cache()


__all__ = [
    "build_dataset_scope_corpus_cache_token",
    "build_document_scope_corpus_cache_token",
    "build_multi_dataset_scope_corpus_cache_token",
    "invalidate_dataset_cache_namespace",
    "resolve_corpus_cache_token",
]

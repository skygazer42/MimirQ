"""Lightweight corpus cache token helpers for retrieval orchestration."""

import json
from collections.abc import Sequence
from typing import Any
from uuid import UUID

from app.rag.core.hashing import stable_hash


def _as_token_part(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def resolve_corpus_cache_token(
    _db: Any,
    *,
    tenant_id: UUID,
    dataset_id: UUID | None = None,
    dataset_ids: Sequence[UUID] | None = None,
    document_ids: Sequence[UUID] | None = None,
) -> str | None:
    parts = {
        "schema": "mimirq.corpus_cache_token.stub.v1",
        "tenant_id": _as_token_part(tenant_id),
        "dataset_id": _as_token_part(dataset_id) if dataset_id is not None else None,
        "dataset_ids": [_as_token_part(v) for v in (dataset_ids or []) if _as_token_part(v)],
        "document_ids": [_as_token_part(v) for v in (document_ids or []) if _as_token_part(v)],
    }
    if not parts["dataset_id"] and not parts["dataset_ids"] and not parts["document_ids"]:
        return None
    raw = json.dumps(parts, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return stable_hash(raw, length=24)


__all__ = ["resolve_corpus_cache_token"]

"""
KG provenance helpers.

This module is intentionally dependency-light so it can be used by both
indexing and API layers without pulling in DB/LLM components.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID


def _safe_uuid_str(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, UUID):
        return str(value)
    try:
        return str(UUID(str(value)))
    except Exception:
        return None


def _safe_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except Exception:
        return None


def _safe_str(value: Any, *, max_len: int) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    return s[: max(0, int(max_len or 0))]


_ALLOWED_REF_INT_KEYS = frozenset(
    {
        "chunk_index",
        "page",
        "start_char",
        "end_char",
        "content_len",
    }
)
_ALLOWED_REF_STR_KEYS = frozenset(
    {
        "chunk_key",
        "content_hash",
        "source",
    }
)


def build_event_entity_provenance(
    *,
    document_id: Any,
    chunk_id: Any,
    references: dict[str, Any] | None,
) -> dict[str, Any]:
    """
    Build a small, JSON-safe provenance dict for a KG edge (event->entity).

    Design:
    - allowlist-only keys (avoid leaking arbitrary nested content)
    - stringified UUIDs
    - bounded strings
    """
    doc_id = _safe_uuid_str(document_id)
    ch_id = _safe_uuid_str(chunk_id)
    refs = references if isinstance(references, dict) else {}

    out: dict[str, Any] = {}
    if doc_id:
        out["document_id"] = doc_id
    if ch_id:
        out["chunk_id"] = ch_id

    for k in _ALLOWED_REF_INT_KEYS:
        v = _safe_int(refs.get(k))
        if v is None:
            continue
        out[k] = v

    for k in _ALLOWED_REF_STR_KEYS:
        v = _safe_str(refs.get(k), max_len=200)
        if v is None:
            continue
        out[k] = v

    return out


__all__ = ["build_event_entity_provenance"]


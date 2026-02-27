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


def build_kg_path_provenance(
    *,
    entities: Any,
    key_entity_ids: set[str] | None,
    max_entities: int = 4,
) -> list[dict[str, str]]:
    """
    Build a small, PII-safe KG "path" payload for KG-injected citations.

    Output format:
      [{"entity_id":"...","type":"..."}]

    Design:
    - No names/descriptions are included (those can leak document text).
    - Deterministic ordering (type, entity_id) so diffs are stable across runs.
    - Bounded length (max_entities).
    """
    if not entities:
        return []

    lim = max(0, int(max_entities or 0))
    if lim <= 0:
        return []

    key_set: set[str] | None = None
    if isinstance(key_entity_ids, set) and key_entity_ids:
        cleaned = {str(x).strip() for x in key_entity_ids if str(x).strip()}
        key_set = cleaned if cleaned else None

    def _entity_id_and_type(obj: Any) -> tuple[str | None, str | None]:
        if obj is None:
            return None, None
        if isinstance(obj, dict):
            ent_id = obj.get("entity_id") or obj.get("id")
            ent_type = obj.get("type")
        else:
            ent_id = getattr(obj, "id", None)
            ent_type = getattr(obj, "type", None)
        ent_id_s = str(ent_id or "").strip()
        ent_type_s = str(ent_type or "").strip()
        return (ent_id_s or None), (ent_type_s or None)

    dedup: dict[str, str] = {}
    items = entities if isinstance(entities, list) else list(entities) if hasattr(entities, "__iter__") else []
    for ent in items:
        ent_id_s, ent_type_s = _entity_id_and_type(ent)
        if not ent_id_s:
            continue
        if key_set is not None and ent_id_s not in key_set:
            continue
        # Keep first seen type (best-effort).
        if ent_id_s not in dedup:
            dedup[ent_id_s] = ent_type_s or "unknown"

    pairs = sorted(((eid, typ) for eid, typ in dedup.items()), key=lambda x: (x[1], x[0]))
    out: list[dict[str, str]] = []
    for eid, typ in pairs[:lim]:
        out.append({"entity_id": str(eid), "type": str(typ or "unknown")})
    return out


__all__ = ["build_event_entity_provenance", "build_kg_path_provenance"]

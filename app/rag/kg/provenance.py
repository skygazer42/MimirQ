"""
KG provenance helpers.

This module is intentionally dependency-light so it can be used by both
indexing and API layers without pulling in DB/LLM components.
"""


from typing import Any
from uuid import UUID


def _safe_uuid_str(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, UUID):
        return str(value)

    return str(UUID(str(value)))



def _safe_int(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)



def _safe_str(value: Any, *, max_len: int) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    return s[: max(0, int(max_len or 0))]


def _iter_items(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if hasattr(value, "__iter__"):
        return list(value)
    return []


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
    items = _iter_items(entities)
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


def build_kg_shortest_path_provenance(
    *,
    event: Any,
    entities: Any,
    key_entity_ids: set[str] | None,
    relations: Any = None,
    bucket_low_max: float = 0.4,
    bucket_mid_max: float = 0.7,
) -> dict[str, Any] | None:
    """
    Build a compact shortest-path provenance payload for an evidence event.

    The path connects 2 entities using one of:
    - entity -> entity (direct relation edge)
    - entity -> event -> entity (shared event)

    Output (PII-safe identifiers only, no names/titles):
      {
        "schema": "mimirq.kg_path_provenance.v1",
        "kind": "entity_relation" | "entity_event_entity",
        "hops": 1 | 2,
        "nodes": [...],
        "edges": [...],
      }
    """

    def _bucket(conf: Any) -> str:
        try:
            c = float(conf or 0.0)
        except Exception:
            c = 0.0
        lo = float(bucket_low_max)
        mid = float(bucket_mid_max)
        if lo >= mid:
            lo, mid = 0.4, 0.7
        if c < lo:
            return "low"
        if c < mid:
            return "mid"
        return "high"

    def _event_id_and_scope(obj: Any) -> tuple[str | None, str | None, str | None]:
        if obj is None:
            return None, None, None
        if isinstance(obj, dict):
            ev_id = obj.get("event_id") or obj.get("id")
            doc_id = obj.get("document_id")
            ch_id = obj.get("chunk_id")
        else:
            ev_id = getattr(obj, "id", None)
            doc_id = getattr(obj, "document_id", None)
            ch_id = getattr(obj, "chunk_id", None)
        return _safe_uuid_str(ev_id), _safe_uuid_str(doc_id), _safe_uuid_str(ch_id)

    def _entity_id_and_type(obj: Any) -> tuple[str | None, str | None]:
        if obj is None:
            return None, None
        if isinstance(obj, dict):
            ent_id = obj.get("entity_id") or obj.get("id")
            ent_type = obj.get("type")
        else:
            ent_id = getattr(obj, "id", None) or getattr(obj, "entity_id", None)
            ent_type = getattr(obj, "type", None)
        ent_id_s = _safe_uuid_str(ent_id)
        ent_type_s = _safe_str(ent_type, max_len=100)
        return ent_id_s, (ent_type_s or "unknown") if ent_id_s else None

    ev_id, ev_doc_id, ev_chunk_id = _event_id_and_scope(event)
    if not ev_id:
        return None

    key_set: set[str] | None = None
    if isinstance(key_entity_ids, set) and key_entity_ids:
        cleaned = {str(x).strip() for x in key_entity_ids if str(x).strip()}
        key_set = cleaned if cleaned else None

    ent_items = _iter_items(entities)
    ents: list[tuple[str, str]] = []
    for e in ent_items:
        ent_id_s, ent_type_s = _entity_id_and_type(e)
        if not ent_id_s or not ent_type_s:
            continue
        if key_set is not None and ent_id_s not in key_set:
            continue
        ents.append((ent_id_s, ent_type_s))

    # Need at least 2 endpoints to form an entity<->entity explanation.
    if len(ents) < 2:
        return None

    ents = sorted(set(ents), key=lambda x: (x[1], x[0]))
    a_id, a_type = ents[0]
    b_id, b_type = ents[1]

    rel_map: dict[frozenset[str], dict[str, Any]] = {}
    rel_items = _iter_items(relations)
    for r in rel_items:
        if r is None:
            continue
        if isinstance(r, dict):
            sid = r.get("subject_entity_id")
            oid = r.get("object_entity_id")
            rel_id = r.get("id")
            predicate = r.get("predicate")
            confidence = r.get("confidence")
            r_doc = r.get("document_id")
            r_chunk = r.get("chunk_id")
            r_event = r.get("event_id")
            refs = r.get("references")
        else:
            sid = getattr(r, "subject_entity_id", None)
            oid = getattr(r, "object_entity_id", None)
            rel_id = getattr(r, "id", None)
            predicate = getattr(r, "predicate", None)
            confidence = getattr(r, "confidence", None)
            r_doc = getattr(r, "document_id", None)
            r_chunk = getattr(r, "chunk_id", None)
            r_event = getattr(r, "event_id", None)
            refs = getattr(r, "references", None)

        sid_s = _safe_uuid_str(sid)
        oid_s = _safe_uuid_str(oid)
        if not sid_s or not oid_s or sid_s == oid_s:
            continue
        key = frozenset({sid_s, oid_s})

        evidence_source = ""
        if isinstance(refs, dict):
            evidence_source = str(refs.get("evidence_source") or "").strip().casefold()

        rel_map.setdefault(
            key,
            {
                "relation_id": _safe_uuid_str(rel_id),
                "predicate": _safe_str(predicate, max_len=200),
                "confidence": confidence,
                "confidence_bucket": _bucket(confidence),
                "evidence_source": evidence_source or None,
                "document_id": _safe_uuid_str(r_doc),
                "chunk_id": _safe_uuid_str(r_chunk),
                "event_id": _safe_uuid_str(r_event),
            },
        )

    direct = rel_map.get(frozenset({a_id, b_id}))
    if direct and direct.get("relation_id"):
        return {
            "schema": "mimirq.kg_path_provenance.v1",
            "kind": "entity_relation",
            "hops": 1,
            "nodes": [
                {"kind": "entity", "entity_id": str(a_id), "type": str(a_type)},
                {"kind": "entity", "entity_id": str(b_id), "type": str(b_type)},
            ],
            "edges": [
                {
                    "kind": "relation",
                    "relation_id": direct.get("relation_id"),
                    "predicate": direct.get("predicate"),
                    "confidence_bucket": direct.get("confidence_bucket"),
                    "evidence_source": direct.get("evidence_source"),
                    "document_id": direct.get("document_id"),
                    "chunk_id": direct.get("chunk_id"),
                    "event_id": direct.get("event_id"),
                }
            ],
        }

    return {
        "schema": "mimirq.kg_path_provenance.v1",
        "kind": "entity_event_entity",
        "hops": 2,
        "nodes": [
            {"kind": "entity", "entity_id": str(a_id), "type": str(a_type)},
            {
                "kind": "event",
                "event_id": str(ev_id),
                "document_id": ev_doc_id,
                "chunk_id": ev_chunk_id,
            },
            {"kind": "entity", "entity_id": str(b_id), "type": str(b_type)},
        ],
        "edges": [
            {
                "kind": "event_entity",
                "entity_id": str(a_id),
                "event_id": str(ev_id),
                "document_id": ev_doc_id,
                "chunk_id": ev_chunk_id,
            },
            {
                "kind": "event_entity",
                "entity_id": str(b_id),
                "event_id": str(ev_id),
                "document_id": ev_doc_id,
                "chunk_id": ev_chunk_id,
            },
        ],
    }


__all__ = ["build_event_entity_provenance", "build_kg_path_provenance", "build_kg_shortest_path_provenance"]

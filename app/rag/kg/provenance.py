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


def _normalized_key_entity_ids(key_entity_ids: set[str] | None) -> set[str] | None:
    if not isinstance(key_entity_ids, set) or not key_entity_ids:
        return None
    cleaned = {str(value).strip() for value in key_entity_ids if str(value).strip()}
    return cleaned or None


def _path_entity_id_and_type(obj: Any) -> tuple[str | None, str | None]:
    if obj is None:
        return None, None
    if isinstance(obj, dict):
        entity_id = obj.get("entity_id") or obj.get("id")
        entity_type = obj.get("type")
    else:
        entity_id = getattr(obj, "id", None)
        entity_type = getattr(obj, "type", None)
    entity_id_text = str(entity_id or "").strip()
    entity_type_text = str(entity_type or "").strip()
    return entity_id_text or None, entity_type_text or None


def _dedup_path_entities(
    entities: Any,
    *,
    key_entity_ids: set[str] | None,
) -> dict[str, str]:
    dedup: dict[str, str] = {}
    for entity in _iter_items(entities):
        entity_id, entity_type = _path_entity_id_and_type(entity)
        if not entity_id:
            continue
        if key_entity_ids is not None and entity_id not in key_entity_ids:
            continue
        dedup.setdefault(entity_id, entity_type or "unknown")
    return dedup


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

    dedup = _dedup_path_entities(
        entities,
        key_entity_ids=_normalized_key_entity_ids(key_entity_ids),
    )
    pairs = sorted(((eid, typ) for eid, typ in dedup.items()), key=lambda x: (x[1], x[0]))
    return [
        {"entity_id": str(entity_id), "type": str(entity_type or "unknown")}
        for entity_id, entity_type in pairs[:lim]
    ]


def _confidence_bucket(confidence: Any, *, low_max: float, mid_max: float) -> str:
    try:
        value = float(confidence or 0.0)
    except Exception:
        value = 0.0
    low = float(low_max)
    middle = float(mid_max)
    if low >= middle:
        low, middle = 0.4, 0.7
    if value < low:
        return "low"
    if value < middle:
        return "mid"
    return "high"


def _event_id_and_scope(obj: Any) -> tuple[str | None, str | None, str | None]:
    if obj is None:
        return None, None, None
    if isinstance(obj, dict):
        event_id = obj.get("event_id") or obj.get("id")
        document_id = obj.get("document_id")
        chunk_id = obj.get("chunk_id")
    else:
        event_id = getattr(obj, "id", None)
        document_id = getattr(obj, "document_id", None)
        chunk_id = getattr(obj, "chunk_id", None)
    return _safe_uuid_str(event_id), _safe_uuid_str(document_id), _safe_uuid_str(chunk_id)


def _shortest_path_entity_id_and_type(obj: Any) -> tuple[str | None, str | None]:
    if obj is None:
        return None, None
    if isinstance(obj, dict):
        entity_id = obj.get("entity_id") or obj.get("id")
        entity_type = obj.get("type")
    else:
        entity_id = getattr(obj, "id", None) or getattr(obj, "entity_id", None)
        entity_type = getattr(obj, "type", None)
    entity_id_text = _safe_uuid_str(entity_id)
    entity_type_text = _safe_str(entity_type, max_len=100)
    return entity_id_text, (entity_type_text or "unknown") if entity_id_text else None


def _shortest_path_entities(
    entities: Any,
    *,
    key_entity_ids: set[str] | None,
) -> list[tuple[str, str]]:
    selected: list[tuple[str, str]] = []
    for entity in _iter_items(entities):
        entity_id, entity_type = _shortest_path_entity_id_and_type(entity)
        if not entity_id or not entity_type:
            continue
        if key_entity_ids is not None and entity_id not in key_entity_ids:
            continue
        selected.append((entity_id, entity_type))
    return sorted(set(selected), key=lambda item: (item[1], item[0]))


def _relation_values(relation: Any) -> tuple[Any, ...] | None:
    if relation is None:
        return None
    if isinstance(relation, dict):
        return (
            relation.get("subject_entity_id"),
            relation.get("object_entity_id"),
            relation.get("id"),
            relation.get("predicate"),
            relation.get("confidence"),
            relation.get("document_id"),
            relation.get("chunk_id"),
            relation.get("event_id"),
            relation.get("references"),
        )
    return (
        getattr(relation, "subject_entity_id", None),
        getattr(relation, "object_entity_id", None),
        getattr(relation, "id", None),
        getattr(relation, "predicate", None),
        getattr(relation, "confidence", None),
        getattr(relation, "document_id", None),
        getattr(relation, "chunk_id", None),
        getattr(relation, "event_id", None),
        getattr(relation, "references", None),
    )


def _relation_path_entry(
    relation: Any,
    *,
    bucket_low_max: float,
    bucket_mid_max: float,
) -> tuple[frozenset[str], dict[str, Any]] | None:
    values = _relation_values(relation)
    if values is None:
        return None
    subject_id, object_id, relation_id, predicate, confidence, document_id, chunk_id, event_id, references = values
    subject_id_text = _safe_uuid_str(subject_id)
    object_id_text = _safe_uuid_str(object_id)
    if not subject_id_text or not object_id_text or subject_id_text == object_id_text:
        return None
    evidence_source = ""
    if isinstance(references, dict):
        evidence_source = str(references.get("evidence_source") or "").strip().casefold()
    return frozenset({subject_id_text, object_id_text}), {
        "relation_id": _safe_uuid_str(relation_id),
        "predicate": _safe_str(predicate, max_len=200),
        "confidence": confidence,
        "confidence_bucket": _confidence_bucket(
            confidence,
            low_max=bucket_low_max,
            mid_max=bucket_mid_max,
        ),
        "evidence_source": evidence_source or None,
        "document_id": _safe_uuid_str(document_id),
        "chunk_id": _safe_uuid_str(chunk_id),
        "event_id": _safe_uuid_str(event_id),
    }


def _relation_path_map(
    relations: Any,
    *,
    bucket_low_max: float,
    bucket_mid_max: float,
) -> dict[frozenset[str], dict[str, Any]]:
    relation_map: dict[frozenset[str], dict[str, Any]] = {}
    for relation in _iter_items(relations):
        entry = _relation_path_entry(
            relation,
            bucket_low_max=bucket_low_max,
            bucket_mid_max=bucket_mid_max,
        )
        if entry is not None:
            relation_map.setdefault(*entry)
    return relation_map


def _direct_relation_provenance(
    *,
    first: tuple[str, str],
    second: tuple[str, str],
    relation: dict[str, Any],
) -> dict[str, Any]:
    first_id, first_type = first
    second_id, second_type = second
    return {
        "schema": "mimirq.kg_path_provenance.v1",
        "kind": "entity_relation",
        "hops": 1,
        "nodes": [
            {"kind": "entity", "entity_id": str(first_id), "type": str(first_type)},
            {"kind": "entity", "entity_id": str(second_id), "type": str(second_type)},
        ],
        "edges": [
            {
                "kind": "relation",
                "relation_id": relation.get("relation_id"),
                "predicate": relation.get("predicate"),
                "confidence_bucket": relation.get("confidence_bucket"),
                "evidence_source": relation.get("evidence_source"),
                "document_id": relation.get("document_id"),
                "chunk_id": relation.get("chunk_id"),
                "event_id": relation.get("event_id"),
            }
        ],
    }


def _event_bridge_provenance(
    *,
    event_scope: tuple[str, str | None, str | None],
    first: tuple[str, str],
    second: tuple[str, str],
) -> dict[str, Any]:
    event_id, document_id, chunk_id = event_scope
    first_id, first_type = first
    second_id, second_type = second
    return {
        "schema": "mimirq.kg_path_provenance.v1",
        "kind": "entity_event_entity",
        "hops": 2,
        "nodes": [
            {"kind": "entity", "entity_id": str(first_id), "type": str(first_type)},
            {"kind": "event", "event_id": str(event_id), "document_id": document_id, "chunk_id": chunk_id},
            {"kind": "entity", "entity_id": str(second_id), "type": str(second_type)},
        ],
        "edges": [
            {
                "kind": "event_entity",
                "entity_id": str(first_id),
                "event_id": str(event_id),
                "document_id": document_id,
                "chunk_id": chunk_id,
            },
            {
                "kind": "event_entity",
                "entity_id": str(second_id),
                "event_id": str(event_id),
                "document_id": document_id,
                "chunk_id": chunk_id,
            },
        ],
    }


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

    ev_id, ev_doc_id, ev_chunk_id = _event_id_and_scope(event)
    if not ev_id:
        return None

    ents = _shortest_path_entities(
        entities,
        key_entity_ids=_normalized_key_entity_ids(key_entity_ids),
    )
    if len(ents) < 2:
        return None
    first, second = ents[:2]
    relation_map = _relation_path_map(
        relations,
        bucket_low_max=bucket_low_max,
        bucket_mid_max=bucket_mid_max,
    )
    direct = relation_map.get(frozenset({first[0], second[0]}))
    if direct and direct.get("relation_id"):
        return _direct_relation_provenance(first=first, second=second, relation=direct)
    return _event_bridge_provenance(
        event_scope=(ev_id, ev_doc_id, ev_chunk_id),
        first=first,
        second=second,
    )


__all__ = ["build_event_entity_provenance", "build_kg_path_provenance", "build_kg_shortest_path_provenance"]

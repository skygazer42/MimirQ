from __future__ import annotations

from itertools import islice
from typing import Any

from app.rag.kg.provenance import build_kg_path_provenance
from app.rag.retrieval.query_phrase_match import query_phrase_match


def event_id(event: Any) -> str:
    return str(getattr(event, "id", "") or "")


def event_document_id(event: Any) -> str:
    return str(getattr(event, "document_id", "") or "").strip()


def event_search_text(event: Any) -> str:
    return f"{getattr(event, 'title', '') or ''} {getattr(event, 'summary', '') or ''} {getattr(event, 'content', '') or ''}"


def phrase_score(query: str, text: str) -> float:
    match = query_phrase_match(query, text)
    return float(match.get("score", 0.0) or 0.0)


def exact_phrase_metadata(query: str, event: Any) -> dict[str, Any]:
    phrase = query_phrase_match(query, event_search_text(event))
    score = float(phrase.get("score", 0.0) or 0.0)
    if score <= 0.0:
        return {}
    matched_phrases = phrase.get("matched_phrases") or []
    return {
        "kg_exact_phrase_score": score,
        "kg_exact_phrase_matches": list(islice(matched_phrases, 4)),
    }


def document_phrase_metadata(query: str, doc_label: str) -> dict[str, Any]:
    score = phrase_score(query, doc_label) if doc_label else 0.0
    if score <= 0.0:
        return {}
    return {"kg_source_document_phrase_score": score}


def clamped_hop(event_hops: dict[str, int] | None, event_id_value: str) -> int:
    if event_hops is None:
        return 1
    try:
        hop = int(event_hops.get(event_id_value, 1) or 1)
    except Exception:
        hop = 1
    return max(1, min(hop, 5))


def shared_key_entity_count(entities: list[Any], key_entity_ids: set[str]) -> int:
    shared = 0
    for entity in entities or []:
        entity_id = str(getattr(entity, "id", "") or "")
        if entity_id and entity_id in key_entity_ids:
            shared += 1
    return max(0, min(shared, 5))


def base_event_extras(event: Any, *, hop: int, shared: int) -> dict[str, Any]:
    return {
        "kg_path_length": int(hop),
        "kg_shared_events": int(shared),
        "kg_evidence_anchored": bool(getattr(event, "chunk_id", None)),
    }


def kg_path_metadata(entities: list[Any], key_entity_ids: set[str]) -> dict[str, Any]:
    path = build_kg_path_provenance(entities=entities, key_entity_ids=key_entity_ids, max_entities=4)
    return {"kg_path": path} if path else {}

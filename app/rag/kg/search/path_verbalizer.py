from collections.abc import Mapping, Sequence
from typing import Any


def _safe_text(value: Any, *, max_len: int = 400) -> str:
    text = str(value or "").strip()
    return text[: max(1, max_len)]


def _entity_lookup(key_entities: Sequence[Mapping[str, Any]] | None) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    for item in key_entities or []:
        if not isinstance(item, Mapping):
            continue
        entity_id = _safe_text(item.get("entity_id") or item.get("id"), max_len=200)
        if not entity_id:
            continue
        out[entity_id] = {
            "name": _safe_text(item.get("name"), max_len=200) or entity_id,
            "type": _safe_text(item.get("type"), max_len=80) or "unknown",
        }
    return out


def _path_entities(
    event: Mapping[str, Any], *, key_entities: Sequence[Mapping[str, Any]] | None
) -> list[dict[str, str]]:
    raw_path = event.get("kg_path")
    if not isinstance(raw_path, list):
        return []
    lookup = _entity_lookup(key_entities)
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in raw_path:
        if not isinstance(item, Mapping):
            continue
        entity_id = _safe_text(item.get("entity_id") or item.get("id"), max_len=200)
        if not entity_id or entity_id in seen:
            continue
        seen.add(entity_id)
        lookup_item = lookup.get(entity_id, {})
        out.append(
            {
                "entity_id": entity_id,
                "name": lookup_item.get("name") or entity_id,
                "type": _safe_text(item.get("type"), max_len=80) or lookup_item.get("type") or "unknown",
            }
        )
        if len(out) >= 6:
            break
    return out


def _matching_report_summary(event_id: str, community_reports: Sequence[Mapping[str, Any]] | None) -> str:
    for report in community_reports or []:
        if not isinstance(report, Mapping):
            continue
        summary = _safe_text(report.get("summary"), max_len=500)
        if summary and any(
            isinstance(item, Mapping) and _safe_text(item.get("id"), max_len=200) == event_id
            for item in report.get("events") or []
        ):
            return summary
    return ""


def build_path_renderings(
    *,
    event: Mapping[str, Any],
    key_entities: Sequence[Mapping[str, Any]] | None,
    query: str | None = None,
    community_reports: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    entities = _path_entities(event, key_entities=key_entities)
    event_id = _safe_text(event.get("id"), max_len=200)
    event_title = _safe_text(event.get("title"), max_len=200)
    if not entities or not event_id or not event_title:
        return {}

    path_labels = [f"{item['name']} [{item['type']}]" for item in entities]
    path_string = "; ".join(f"{label} -> {event_title}" for label in path_labels)

    verbalized_triples = [
        f'{item["name"]} ({item["type"]}) is associated with event "{event_title}".' for item in entities
    ]

    graph_nodes = [
        {
            "id": item["entity_id"],
            "label": item["name"],
            "kind": "entity",
            "type": item["type"],
        }
        for item in entities
    ]
    graph_nodes.append(
        {
            "id": event_id,
            "label": event_title,
            "kind": "event",
            "type": "event",
        }
    )

    graph_edges = [
        {
            "source": item["entity_id"],
            "target": event_id,
            "relation": "associated_with_event",
        }
        for item in entities
    ]

    query_text = _safe_text(query, max_len=300)
    reasoning_parts = []
    if query_text:
        reasoning_parts.append(f"Query asks: {query_text}.")
    reasoning_parts.append(f"KG path surfaces {path_string}.")
    summary = _safe_text(event.get("summary"), max_len=240)
    if summary:
        reasoning_parts.append(f"Event summary: {summary}.")

    out: dict[str, Any] = {
        "schema": "mimirq.kg_path_renderings.v1",
        "path_string": path_string,
        "verbalized_triples": verbalized_triples,
        "graph_prompt": {
            "nodes": graph_nodes,
            "edges": graph_edges,
        },
        "reasoning_chain": " ".join(reasoning_parts),
    }

    community_context = _matching_report_summary(event_id, community_reports)
    if community_context:
        out["community_context"] = community_context
    return out


def attach_path_renderings(
    *,
    events: Sequence[dict[str, Any]] | None,
    key_entities: Sequence[Mapping[str, Any]] | None,
    query: str | None = None,
    community_reports: Sequence[Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in events or []:
        if not isinstance(item, dict):
            continue
        current = dict(item)
        renderings = build_path_renderings(
            event=current,
            key_entities=key_entities,
            query=query,
            community_reports=community_reports,
        )
        if renderings:
            current["kg_path_renderings"] = renderings
        out.append(current)
    return out


__all__ = ["attach_path_renderings", "build_path_renderings"]

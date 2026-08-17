"""
Community detection + community/global summaries for KG search.

Goal (Gap 2 in rag_capability_gap_analysis):
- Provide a GraphRAG-like "global search" surface by clustering a recall subgraph into
  communities and producing compact community reports + a global overview summary.

Design constraints:
- No heavy dependencies (networkx/igraph/leidenalg).
- Deterministic output (stable ordering + tie-breakers).
- Feature-flagged: default OFF; must not change existing KG behavior unless enabled.

This module intentionally works on a *recall subgraph* (the events/entities already recalled
for a query) instead of running community detection over the entire dataset graph. This keeps
latency bounded and avoids ACL/versioning pitfalls.
"""

from dataclasses import dataclass
from typing import Any

from app.rag.llm.base import BaseLLMClient
from app.rag.llm.models import LLMMessage, LLMRole


@dataclass(frozen=True)
class CommunityEdge:
    a: str
    b: str
    w: float


def _safe_float(v: object, *, default: float = 0.0) -> float:
    try:
        return float(v)  # type: ignore[arg-type]
    except Exception:
        return float(default)


def _stable_sig(s: str) -> str:
    # For deterministic tie-breaking: ASCII -> casefold; non-ASCII -> keep.
    s = str(s or "").strip()
    return s.casefold() if s.isascii() else s


def _community_level(report: dict[str, Any]) -> int:
    value = (report or {}).get("community_level")
    if value is None:
        value = (report or {}).get("level")
    try:
        return max(0, int(value or 0))
    except Exception:
        return 0


def _community_rank_key(report: dict[str, Any]) -> tuple[float, int, int, str, str]:
    community_id = str((report or {}).get("community_id") or "").strip()
    return (
        -_safe_float((report or {}).get("score"), default=0.0),
        -int((report or {}).get("event_count") or 0),
        -int((report or {}).get("entity_count") or 0),
        _stable_sig(community_id),
        community_id,
    )


def _dedupe_event_entities(entities: list[str], *, max_entities: int) -> list[str]:
    seen: set[str] = set()
    dedup: list[str] = []
    for entity in entities or []:
        entity_id = str(entity or "").strip()
        sig = _stable_sig(entity_id)
        if entity_id and sig not in seen:
            seen.add(sig)
            dedup.append(entity_id)
    dedup.sort(key=lambda item: (_stable_sig(item), item))
    limit = max(0, int(max_entities or 0))
    return dedup[:limit] if limit and len(dedup) > limit else dedup


def _iter_entity_pairs(entities: list[str]):
    for index, left in enumerate(entities[:-1]):
        for right in entities[index + 1 :]:
            if left != right:
                yield (left, right) if left < right else (right, left)


def _edge_counts(event_entities: dict[str, list[str]], *, max_entities_per_event: int) -> dict[tuple[str, str], float]:
    counts: dict[tuple[str, str], float] = {}
    for ents in (event_entities or {}).values():
        dedup = _dedupe_event_entities(ents, max_entities=max_entities_per_event)
        for key in _iter_entity_pairs(dedup):
            counts[key] = float(counts.get(key, 0.0) or 0.0) + 1.0
    return counts


def _community_edges_from_counts(counts: dict[tuple[str, str], float], *, min_weight: float) -> list[CommunityEdge]:
    edges = [
        CommunityEdge(a=a, b=b, w=float(weight)) for (a, b), weight in counts.items() if float(weight) >= min_weight
    ]
    edges.sort(key=lambda edge: (-float(edge.w), _stable_sig(edge.a), _stable_sig(edge.b), edge.a, edge.b))
    return edges


def build_entity_cooccurrence_edges(
    *,
    event_entities: dict[str, list[str]],
    max_entities_per_event: int,
    min_edge_weight: float,
) -> list[CommunityEdge]:
    """
    Build an entity co-occurrence graph from event->entities associations.

    Edge weight is co-occurrence count across events.
    """
    min_w = float(min_edge_weight or 0.0)
    return _community_edges_from_counts(
        _edge_counts(event_entities, max_entities_per_event=max_entities_per_event),
        min_weight=min_w,
    )


def build_multi_level_community_selection(
    *,
    reports: list[dict[str, Any]],
    query_scope: str,
    max_reports: int,
) -> dict[str, Any]:
    clean_reports = [dict(report) for report in (reports or []) if isinstance(report, dict)]
    levels_present = sorted({_community_level(report) for report in clean_reports})
    limit = max(0, int(max_reports or 0))
    scope = _normalized_query_scope(query_scope)

    return {
        "schema": "mimirq.kg_community_selection.v1",
        "query_scope": scope,
        "levels_present": levels_present,
        "selected_reports": _select_community_reports(clean_reports, scope=scope, limit=limit),
    }


def _normalized_query_scope(query_scope: str) -> str:
    scope = str(query_scope or "").strip().lower() or "global"
    return scope if scope in {"global", "local", "drift"} else "global"


def _reports_by_level(reports: list[dict[str, Any]], *, deep: bool = False) -> list[dict[str, Any]]:
    direction = -1 if deep else 1
    return sorted(reports, key=lambda report: (direction * _community_level(report), _community_rank_key(report)))


def _community_id(report: dict[str, Any]) -> str:
    return str((report or {}).get("community_id") or "").strip()


def _select_drift_reports(reports: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    selected = _reports_by_level(reports)[:1]
    selected_ids = {_community_id(report) for report in selected}
    for report in _reports_by_level(reports, deep=True):
        community_id = _community_id(report)
        if community_id in selected_ids:
            continue
        selected.append(report)
        selected_ids.add(community_id)
        if len(selected) >= limit:
            break
    return selected[:limit]


def _select_community_reports(reports: list[dict[str, Any]], *, scope: str, limit: int) -> list[dict[str, Any]]:
    if limit <= 0 or not reports:
        return []
    if scope == "local":
        return _reports_by_level(reports, deep=True)[:limit]
    if scope == "drift":
        return _select_drift_reports(reports, limit=limit)
    return _reports_by_level(reports)[:limit]


def label_propagation_communities(
    *,
    nodes: list[str],
    edges: list[CommunityEdge],
    max_iters: int,
) -> dict[str, str]:
    """
    Deterministic weighted label propagation.

    Returns:
        mapping: node_id -> community_label (one node id used as stable label).
    """
    nodes_in = [str(n or "").strip() for n in (nodes or []) if str(n or "").strip()]
    nodes_sorted = sorted(set(nodes_in), key=lambda x: (_stable_sig(x), x))
    if not nodes_sorted:
        return {}

    adj = _label_adjacency(nodes_sorted, edges)
    label: dict[str, str] = {n: n for n in nodes_sorted}
    iters = max(0, int(max_iters or 0))
    if iters <= 0:
        return label

    for _ in range(iters):
        if _propagate_labels_once(nodes_sorted, adj, label) == 0:
            break

    return label


def _label_adjacency(nodes: list[str], edges: list[CommunityEdge]) -> dict[str, list[tuple[str, float]]]:
    adj: dict[str, list[tuple[str, float]]] = {node: [] for node in nodes}
    for edge in edges or []:
        a = str(getattr(edge, "a", "") or "").strip()
        b = str(getattr(edge, "b", "") or "").strip()
        weight = _safe_float(getattr(edge, "w", 0.0), default=0.0)
        if a in adj and b in adj and a != b and weight > 0:
            adj[a].append((b, weight))
            adj[b].append((a, weight))
    for node, neighbors in adj.items():
        neighbors.sort(key=lambda item: (-float(item[1]), _stable_sig(item[0]), item[0]))
        adj[node] = neighbors
    return adj


def _neighbor_label_scores(neighbors: list[tuple[str, float]], label: dict[str, str]) -> dict[str, float]:
    scores: dict[str, float] = {}
    for neighbor, weight in neighbors:
        current_label = label.get(neighbor, neighbor)
        scores[current_label] = float(scores.get(current_label, 0.0) or 0.0) + float(weight)
    return scores


def _preferred_label(candidate: str, candidate_score: float, best: str, best_score: float) -> tuple[str, float]:
    if candidate_score > best_score + 1e-12:
        return candidate, candidate_score
    if abs(candidate_score - best_score) <= 1e-12 and (_stable_sig(candidate), candidate) < (_stable_sig(best), best):
        return candidate, candidate_score
    return best, best_score


def _best_neighbor_label(node: str, neighbors: list[tuple[str, float]], label: dict[str, str]) -> str:
    scores = _neighbor_label_scores(neighbors, label)
    best_label = label.get(node, node)
    best_score = scores.get(best_label, float("-inf"))
    for candidate, score in scores.items():
        best_label, best_score = _preferred_label(candidate, score, best_label, best_score)
    return best_label


def _propagate_labels_once(
    nodes: list[str],
    adjacency: dict[str, list[tuple[str, float]]],
    label: dict[str, str],
) -> int:
    changed = 0
    for node in nodes:
        neighbors = adjacency.get(node) or []
        if not neighbors:
            continue
        best_label = _best_neighbor_label(node, neighbors, label)
        if best_label != label.get(node, node):
            label[node] = best_label
            changed += 1
    return changed


def assign_events_to_communities(
    *,
    event_entities: dict[str, list[str]],
    entity_to_label: dict[str, str],
    entity_weights: dict[str, float] | None = None,
) -> dict[str, str]:
    """
    Assign each event to one community label based on its entities.

    Strategy:
    - For each event, compute per-community score as sum(entity_weights) (fallback 1.0 per entity).
    - Pick community with max score; tie-break by label stable signature.
    """
    weights = entity_weights or {}
    out: dict[str, str] = {}
    for ev_id, ents in (event_entities or {}).items():
        ev = str(ev_id or "").strip()
        if not ev:
            continue
        scores = _event_community_scores(ents, entity_to_label=entity_to_label, entity_weights=weights)
        if not scores:
            continue
        best = min(scores.keys(), key=lambda k, scores=scores: (-float(scores[k]), _stable_sig(k), k))
        out[ev] = best
    return out


def _event_community_scores(
    entities: list[str],
    *,
    entity_to_label: dict[str, str],
    entity_weights: dict[str, float],
) -> dict[str, float]:
    scores: dict[str, float] = {}
    for ent in entities or []:
        entity_id = str(ent or "").strip()
        label = entity_to_label.get(entity_id)
        if label:
            weight = float(entity_weights.get(entity_id, 1.0) or 1.0)
            scores[label] = float(scores.get(label, 0.0) or 0.0) + weight
    return scores


def _entity_record(entity: dict[str, Any]) -> tuple[str, dict[str, Any], float] | None:
    entity_id = str(entity.get("entity_id") or entity.get("id") or "").strip()
    if not entity_id:
        return None
    record = {
        "entity_id": entity_id,
        "name": str(entity.get("name") or "").strip(),
        "type": str(entity.get("type") or "").strip() or "unknown",
        "weight": _safe_float(entity.get("weight"), default=0.0),
    }
    return entity_id, record, float(record["weight"])


def _index_entities(entities: list[dict[str, Any]]) -> tuple[dict[str, dict[str, Any]], dict[str, float], list[str]]:
    ent_info: dict[str, dict[str, Any]] = {}
    ent_weights: dict[str, float] = {}
    nodes: list[str] = []
    for entity in entities or []:
        if not isinstance(entity, dict):
            continue
        record = _entity_record(entity)
        if record is None:
            continue
        entity_id, info, weight = record
        nodes.append(entity_id)
        ent_info[entity_id] = info
        ent_weights[entity_id] = weight
    return ent_info, ent_weights, sorted(set(nodes), key=lambda item: (_stable_sig(item), item))


def _filter_event_entities(event_entities: dict[str, list[str]], *, node_set: set[str]) -> dict[str, list[str]]:
    ev_map: dict[str, list[str]] = {}
    for ev_id, entities in (event_entities or {}).items():
        event_id = str(ev_id or "").strip()
        filtered = [str(entity or "").strip() for entity in (entities or []) if str(entity or "").strip() in node_set]
        if event_id and filtered:
            ev_map[event_id] = filtered
    return ev_map


def _index_events(events: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    ev_info: dict[str, dict[str, Any]] = {}
    for event in events or []:
        if isinstance(event, dict):
            event_id = str(event.get("id") or event.get("event_id") or "").strip()
            if event_id:
                ev_info[event_id] = event
    return ev_info


def _community_entity_map(entity_to_label: dict[str, str], entity_weights: dict[str, float]) -> dict[str, list[str]]:
    community_entities: dict[str, list[str]] = {}
    for entity_id, label in entity_to_label.items():
        community_entities.setdefault(label, []).append(entity_id)
    for entity_ids in community_entities.values():
        entity_ids.sort(key=lambda item: (-float(entity_weights.get(item, 0.0) or 0.0), _stable_sig(item), item))
    return community_entities


def _community_event_map(event_to_label: dict[str, str]) -> dict[str, list[str]]:
    community_events: dict[str, list[str]] = {}
    for event_id, label in event_to_label.items():
        community_events.setdefault(label, []).append(event_id)
    for event_ids in community_events.values():
        event_ids.sort(key=lambda item: (_stable_sig(item), item))
    return community_events


def _ranked_community_labels(
    community_entities: dict[str, list[str]],
    community_events: dict[str, list[str]],
    *,
    max_communities: int,
) -> list[str]:
    labels = sorted(
        community_entities.keys(),
        key=lambda label: (
            -int(len(community_events.get(label, []) or [])),
            -int(len(community_entities.get(label, []) or [])),
            _stable_sig(label),
            label,
        ),
    )
    return labels[:max_communities] if max_communities > 0 else labels


def _top_entities(
    entity_ids: list[str], ent_info: dict[str, dict[str, Any]], *, max_entities: int
) -> list[dict[str, Any]]:
    limit = max(0, int(max_entities or 0)) or len(entity_ids)
    return [ent_info.get(entity_id) or {"entity_id": entity_id} for entity_id in entity_ids[:limit]]


def _scored_events(event_ids: list[str], ev_info: dict[str, dict[str, Any]]) -> list[tuple[float, str]]:
    scored = [
        (_safe_float((ev_info.get(event_id) or {}).get("score"), default=0.0), event_id) for event_id in event_ids
    ]
    return sorted(scored, key=lambda item: (-float(item[0]), _stable_sig(item[1]), item[1]))


def _top_events(event_ids: list[str], ev_info: dict[str, dict[str, Any]], *, max_events: int) -> list[dict[str, Any]]:
    scored = _scored_events(event_ids, ev_info)
    limit = max(0, int(max_events or 0)) or len(scored)
    return [
        event
        for _score, event_id in scored[:limit]
        if isinstance((event := ev_info.get(event_id) or {"id": event_id}), dict)
    ]


def _community_summary(entities: list[dict[str, Any]], events: list[dict[str, Any]]) -> str:
    ent_names = [str(entity.get("name") or "").strip() for entity in entities if isinstance(entity, dict)]
    ev_titles = [str(event.get("title") or "").strip() for event in events if isinstance(event, dict)]
    ent_names = [name for name in ent_names if name][:8]
    ev_titles = [title for title in ev_titles if title][:6]
    if ent_names and ev_titles:
        return f"Top entities: {', '.join(ent_names)}. Representative events: " + "; ".join(ev_titles) + "."
    if ent_names:
        return f"Top entities: {', '.join(ent_names)}."
    if ev_titles:
        return "Representative events: " + "; ".join(ev_titles) + "."
    return ""


def _build_community_report(
    *,
    idx: int,
    label: str,
    entity_ids: list[str],
    event_ids: list[str],
    ent_info: dict[str, dict[str, Any]],
    ev_info: dict[str, dict[str, Any]],
    max_entities_per_community: int,
    max_events_per_community: int,
) -> dict[str, Any]:
    top_entities = _top_entities(entity_ids, ent_info, max_entities=max_entities_per_community)
    top_events = _top_events(event_ids, ev_info, max_events=max_events_per_community)
    return {
        "schema": "mimirq.kg_community_report.v1",
        "community_id": str(idx),
        "label": label,
        "entity_count": int(len(entity_ids)),
        "event_count": int(len(event_ids)),
        "entities": top_entities,
        "events": top_events,
        "summary": _community_summary(top_entities, top_events),
    }


def _build_global_summary(reports: list[dict[str, Any]], *, max_chars: int) -> str:
    parts = [f"Found {len(reports)} communities in the recalled KG subgraph."]
    for report in reports:
        summary = str(report.get("summary") or "").strip()
        if summary:
            parts.append(f"[Community {report.get('community_id')}] {summary}")
    global_summary = "\n".join(parts).strip()
    limit = max(0, int(max_chars or 0))
    return global_summary[:limit].rstrip() + "..." if limit and len(global_summary) > limit else global_summary


def _community_entity_lines(entities: list[Any]) -> list[str]:
    lines: list[str] = []
    for entity in entities[:15]:
        if isinstance(entity, dict):
            name = str(entity.get("name") or entity.get("entity_id") or "").strip()
            entity_type = str(entity.get("type") or "unknown").strip() or "unknown"
            if name:
                lines.append(f"- {name} ({entity_type})")
    return lines


def _community_event_lines(events: list[Any]) -> list[str]:
    lines: list[str] = []
    for event in events[:10]:
        if isinstance(event, dict):
            title = str(event.get("title") or event.get("summary") or event.get("id") or "").strip()
            if title:
                lines.append(f"- {title}")
    return lines


def _lazy_summary_prompt(*, query: str, entity_lines: list[str], event_lines: list[str]) -> str:
    return (
        "Summarize the following knowledge graph community in the context of the user query.\n"
        "Focus on information relevant to the query. Be concise (2-3 sentences).\n\n"
        f"User Query: {str(query or '').strip()}\n\n"
        "Community Entities:\n"
        f"{chr(10).join(entity_lines) if entity_lines else '- (none)'}\n\n"
        "Community Events:\n"
        f"{chr(10).join(event_lines) if event_lines else '- (none)'}\n\n"
        "Community Summary:"
    )


def build_community_reports(
    *,
    entities: list[dict[str, Any]],
    events: list[dict[str, Any]],
    event_entities: dict[str, list[str]],
    max_entities_per_event: int,
    min_edge_weight: float,
    label_propagation_iters: int,
    max_communities: int,
    max_entities_per_community: int,
    max_events_per_community: int,
    global_summary_max_chars: int,
) -> tuple[list[dict[str, Any]], str]:
    """
    Build community reports and a compact global summary string.

    Inputs are deliberately plain dict/list to keep this module decoupled from SQLAlchemy.
    """
    ent_info, ent_weights, nodes = _index_entities(entities)
    if not nodes:
        return [], ""

    ev_map = _filter_event_entities(event_entities, node_set=set(nodes))
    edges = build_entity_cooccurrence_edges(
        event_entities=ev_map,
        max_entities_per_event=max_entities_per_event,
        min_edge_weight=min_edge_weight,
    )
    ent_to_label = label_propagation_communities(nodes=nodes, edges=edges, max_iters=label_propagation_iters)
    if not ent_to_label:
        return [], ""

    event_to_label = assign_events_to_communities(
        event_entities=ev_map, entity_to_label=ent_to_label, entity_weights=ent_weights
    )
    ev_info = _index_events(events)
    comm_entities = _community_entity_map(ent_to_label, ent_weights)
    comm_events = _community_event_map(event_to_label)
    labels = _ranked_community_labels(comm_entities, comm_events, max_communities=max_communities)

    reports: list[dict[str, Any]] = []
    for idx, lb in enumerate(labels, 1):
        reports.append(
            _build_community_report(
                idx=idx,
                label=lb,
                entity_ids=comm_entities.get(lb, []) or [],
                event_ids=comm_events.get(lb, []) or [],
                ent_info=ent_info,
                ev_info=ev_info,
                max_entities_per_community=max_entities_per_community,
                max_events_per_community=max_events_per_community,
            )
        )

    return reports, _build_global_summary(reports, max_chars=global_summary_max_chars)


async def lazy_summarize(
    *,
    community_report: dict[str, Any],
    query: str,
    llm_client: BaseLLMClient,
    max_tokens: int = 300,
) -> str:
    """
    Generate a query-aware community summary lazily at search time.

    This is intentionally best-effort and compact to keep latency/cost bounded.
    """
    entities = community_report.get("entities", []) if isinstance(community_report, dict) else []
    events = community_report.get("events", []) if isinstance(community_report, dict) else []
    prompt = _lazy_summary_prompt(
        query=query,
        entity_lines=_community_entity_lines(entities),
        event_lines=_community_event_lines(events),
    )

    response = await llm_client.chat(
        [LLMMessage(role=LLMRole.USER, content=prompt)],
        temperature=0.3,
        max_tokens=max(1, int(max_tokens or 300)),
    )
    return str(getattr(response, "content", "") or "").strip()


__all__ = [
    "CommunityEdge",
    "assign_events_to_communities",
    "build_community_reports",
    "build_entity_cooccurrence_edges",
    "lazy_summarize",
    "label_propagation_communities",
]

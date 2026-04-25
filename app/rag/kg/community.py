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

from __future__ import annotations

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
    max_per = max(0, int(max_entities_per_event or 0))
    min_w = float(min_edge_weight or 0.0)

    # Use a sorted tuple key for deterministic accumulation.
    counts: dict[tuple[str, str], float] = {}
    for _ev_id, ents in (event_entities or {}).items():
        if not ents:
            continue
        uniq = [str(e or "").strip() for e in ents if str(e or "").strip()]
        if not uniq:
            continue
        # Deterministic: stable unique + sorted (by stable signature, then raw).
        seen: set[str] = set()
        dedup: list[str] = []
        for e in uniq:
            sig = _stable_sig(e)
            if sig in seen:
                continue
            seen.add(sig)
            dedup.append(e)
        dedup.sort(key=lambda x: (_stable_sig(x), x))
        if max_per and len(dedup) > max_per:
            dedup = dedup[:max_per]
        if len(dedup) < 2:
            continue
        for i in range(len(dedup) - 1):
            for j in range(i + 1, len(dedup)):
                a = dedup[i]
                b = dedup[j]
                if a == b:
                    continue
                key = (a, b) if a < b else (b, a)
                counts[key] = float(counts.get(key, 0.0) or 0.0) + 1.0

    edges: list[CommunityEdge] = []
    for (a, b), w in counts.items():
        w = float(w)
        if w < min_w:
            continue
        edges.append(CommunityEdge(a=a, b=b, w=w))
    # Deterministic order: weight desc, (a,b) asc.
    edges.sort(key=lambda e: (-float(e.w), _stable_sig(e.a), _stable_sig(e.b), e.a, e.b))
    return edges


def build_multi_level_community_selection(
    *,
    reports: list[dict[str, Any]],
    query_scope: str,
    max_reports: int,
) -> dict[str, Any]:
    clean_reports = [dict(report) for report in (reports or []) if isinstance(report, dict)]
    levels_present = sorted({_community_level(report) for report in clean_reports})
    limit = max(0, int(max_reports or 0))
    scope = str(query_scope or "").strip().lower() or "global"
    if scope not in {"global", "local", "drift"}:
        scope = "global"

    selected: list[dict[str, Any]] = []
    if limit > 0 and clean_reports:
        if scope == "global":
            selected = sorted(clean_reports, key=lambda report: (_community_level(report), _community_rank_key(report)))[:limit]
        elif scope == "local":
            selected = sorted(clean_reports, key=lambda report: (-_community_level(report), _community_rank_key(report)))[:limit]
        else:
            by_coarse = sorted(clean_reports, key=lambda report: (_community_level(report), _community_rank_key(report)))
            if by_coarse:
                selected.append(by_coarse[0])
            selected_ids = {str(report.get("community_id") or "").strip() for report in selected}
            by_deep = sorted(clean_reports, key=lambda report: (-_community_level(report), _community_rank_key(report)))
            for report in by_deep:
                community_id = str(report.get("community_id") or "").strip()
                if community_id in selected_ids:
                    continue
                selected.append(report)
                selected_ids.add(community_id)
                if len(selected) >= limit:
                    break
            selected = selected[:limit]

    return {
        "schema": "mimirq.kg_community_selection.v1",
        "query_scope": scope,
        "levels_present": levels_present,
        "selected_reports": selected,
    }


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

    # Build adjacency: node -> list[(neighbor, weight)]
    adj: dict[str, list[tuple[str, float]]] = {n: [] for n in nodes_sorted}
    for e in edges or []:
        a = str(getattr(e, "a", "") or "").strip()
        b = str(getattr(e, "b", "") or "").strip()
        w = _safe_float(getattr(e, "w", 0.0), default=0.0)
        if not a or not b or a == b or w <= 0:
            continue
        if a not in adj or b not in adj:
            # Ignore edges outside node set.
            continue
        adj[a].append((b, w))
        adj[b].append((a, w))

    # Stable adjacency ordering (so tie-breakers are deterministic).
    for n in nodes_sorted:
        nbrs = adj.get(n) or []
        nbrs.sort(key=lambda t: (-float(t[1]), _stable_sig(t[0]), t[0]))
        adj[n] = nbrs

    label: dict[str, str] = {n: n for n in nodes_sorted}
    iters = max(0, int(max_iters or 0))
    if iters <= 0:
        return label

    for _ in range(iters):
        changed = 0
        for n in nodes_sorted:
            nbrs = adj.get(n) or []
            if not nbrs:
                continue
            scores: dict[str, float] = {}
            for nb, w in nbrs:
                lb = label.get(nb, nb)
                scores[lb] = float(scores.get(lb, 0.0) or 0.0) + float(w)
            if not scores:
                continue
            best_label = label.get(n, n)
            best_score = scores.get(best_label, float("-inf"))
            # Choose the highest score; tie-break on lexicographically smallest stable signature.
            for cand, sc in scores.items():
                if sc > best_score + 1e-12:
                    best_label = cand
                    best_score = sc
                elif abs(sc - best_score) <= 1e-12:
                    if (_stable_sig(cand), cand) < (_stable_sig(best_label), best_label):
                        best_label = cand
                        best_score = sc
            if best_label != label.get(n, n):
                label[n] = best_label
                changed += 1
        if changed == 0:
            break

    return label


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
        scores: dict[str, float] = {}
        for ent in ents or []:
            e = str(ent or "").strip()
            if not e:
                continue
            lb = entity_to_label.get(e)
            if not lb:
                continue
            w = float(weights.get(e, 1.0) or 1.0)
            scores[lb] = float(scores.get(lb, 0.0) or 0.0) + w
        if not scores:
            continue
        best = min(scores.keys(), key=lambda k, scores=scores: (-float(scores[k]), _stable_sig(k), k))
        out[ev] = best
    return out


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
    ent_info: dict[str, dict[str, Any]] = {}
    ent_weights: dict[str, float] = {}
    nodes: list[str] = []
    for ent in entities or []:
        if not isinstance(ent, dict):
            continue
        eid = str(ent.get("entity_id") or ent.get("id") or "").strip()
        if not eid:
            continue
        nodes.append(eid)
        ent_info[eid] = {
            "entity_id": eid,
            "name": str(ent.get("name") or "").strip(),
            "type": str(ent.get("type") or "").strip() or "unknown",
            "weight": _safe_float(ent.get("weight"), default=0.0),
        }
        ent_weights[eid] = float(ent_info[eid]["weight"])

    nodes = sorted(set(nodes), key=lambda x: (_stable_sig(x), x))
    if not nodes:
        return [], ""

    # Filter event_entities to the current node set.
    node_set = set(nodes)
    ev_map: dict[str, list[str]] = {}
    for ev_id, ents in (event_entities or {}).items():
        ev = str(ev_id or "").strip()
        if not ev:
            continue
        filtered = [str(e or "").strip() for e in (ents or []) if str(e or "").strip() in node_set]
        if not filtered:
            continue
        ev_map[ev] = filtered

    edges = build_entity_cooccurrence_edges(
        event_entities=ev_map,
        max_entities_per_event=max_entities_per_event,
        min_edge_weight=min_edge_weight,
    )
    ent_to_label = label_propagation_communities(nodes=nodes, edges=edges, max_iters=label_propagation_iters)
    if not ent_to_label:
        return [], ""

    event_to_label = assign_events_to_communities(event_entities=ev_map, entity_to_label=ent_to_label, entity_weights=ent_weights)

    # Index event info (title/summary/score) best-effort.
    ev_info: dict[str, dict[str, Any]] = {}
    for ev in events or []:
        if not isinstance(ev, dict):
            continue
        ev_id = str(ev.get("id") or ev.get("event_id") or "").strip()
        if not ev_id:
            continue
        ev_info[ev_id] = ev

    # Build communities.
    comm_entities: dict[str, list[str]] = {}
    for eid, lb in ent_to_label.items():
        comm_entities.setdefault(lb, []).append(eid)
    for lb in comm_entities:
        comm_entities[lb].sort(key=lambda x: (-float(ent_weights.get(x, 0.0) or 0.0), _stable_sig(x), x))

    comm_events: dict[str, list[str]] = {}
    for ev_id, lb in event_to_label.items():
        comm_events.setdefault(lb, []).append(ev_id)
    for lb in comm_events:
        comm_events[lb].sort(key=lambda x: (_stable_sig(x), x))

    # Rank communities by (#events desc, #entities desc, label).
    labels = sorted(
        comm_entities.keys(),
        key=lambda lb: (
            -int(len(comm_events.get(lb, []) or [])),
            -int(len(comm_entities.get(lb, []) or [])),
            _stable_sig(lb),
            lb,
        ),
    )
    if max_communities > 0:
        labels = labels[: max_communities]

    reports: list[dict[str, Any]] = []
    for idx, lb in enumerate(labels, 1):
        ent_ids = comm_entities.get(lb, []) or []
        ev_ids = comm_events.get(lb, []) or []

        top_ents: list[dict[str, Any]] = []
        for eid in ent_ids[: max(0, int(max_entities_per_community or 0)) or len(ent_ids)]:
            top_ents.append(ent_info.get(eid) or {"entity_id": eid})

        # Prefer events with explicit scores if present.
        scored_events: list[tuple[float, str]] = []
        for ev_id in ev_ids:
            score = 0.0
            ev = ev_info.get(ev_id) or {}
            if isinstance(ev, dict):
                score = _safe_float(ev.get("score"), default=0.0)
            scored_events.append((score, ev_id))
        scored_events.sort(key=lambda t: (-float(t[0]), _stable_sig(t[1]), t[1]))

        top_ev_items: list[dict[str, Any]] = []
        limit_events = max(0, int(max_events_per_community or 0)) or len(scored_events)
        for _score, ev_id in scored_events[:limit_events]:
            ev = ev_info.get(ev_id) or {"id": ev_id}
            if isinstance(ev, dict):
                top_ev_items.append(ev)

        # Deterministic "report summary" (LLM-free).
        ent_names = [str(e.get("name") or "").strip() for e in top_ents if isinstance(e, dict)]
        ent_names = [x for x in ent_names if x]
        ent_names = ent_names[:8]
        ev_titles = [str(e.get("title") or "").strip() for e in top_ev_items if isinstance(e, dict)]
        ev_titles = [x for x in ev_titles if x]
        ev_titles = ev_titles[:6]

        if ent_names and ev_titles:
            summary = f"Top entities: {', '.join(ent_names)}. Representative events: " + "; ".join(ev_titles) + "."
        elif ent_names:
            summary = f"Top entities: {', '.join(ent_names)}."
        elif ev_titles:
            summary = "Representative events: " + "; ".join(ev_titles) + "."
        else:
            summary = ""

        reports.append(
            {
                "schema": "mimirq.kg_community_report.v1",
                "community_id": str(idx),
                "label": lb,
                "entity_count": int(len(ent_ids)),
                "event_count": int(len(ev_ids)),
                "entities": top_ents,
                "events": top_ev_items,
                "summary": summary,
            }
        )

    # Global summary: compact multi-community overview.
    parts: list[str] = []
    parts.append(f"Found {len(reports)} communities in the recalled KG subgraph.")
    for rep in reports:
        cid = rep.get("community_id")
        summ = str(rep.get("summary") or "").strip()
        if summ:
            parts.append(f"[Community {cid}] {summ}")
    global_summary = "\n".join(parts).strip()
    max_chars = max(0, int(global_summary_max_chars or 0))
    if max_chars and len(global_summary) > max_chars:
        global_summary = global_summary[:max_chars].rstrip() + "..."

    return reports, global_summary


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

    entity_lines: list[str] = []
    for ent in entities[:15]:
        if not isinstance(ent, dict):
            continue
        name = str(ent.get("name") or ent.get("entity_id") or "").strip()
        if not name:
            continue
        etype = str(ent.get("type") or "unknown").strip() or "unknown"
        entity_lines.append(f"- {name} ({etype})")

    event_lines: list[str] = []
    for ev in events[:10]:
        if not isinstance(ev, dict):
            continue
        title = str(ev.get("title") or ev.get("summary") or ev.get("id") or "").strip()
        if not title:
            continue
        event_lines.append(f"- {title}")

    prompt = (
        "Summarize the following knowledge graph community in the context of the user query.\n"
        "Focus on information relevant to the query. Be concise (2-3 sentences).\n\n"
        f"User Query: {str(query or '').strip()}\n\n"
        "Community Entities:\n"
        f"{chr(10).join(entity_lines) if entity_lines else '- (none)'}\n\n"
        "Community Events:\n"
        f"{chr(10).join(event_lines) if event_lines else '- (none)'}\n\n"
        "Community Summary:"
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

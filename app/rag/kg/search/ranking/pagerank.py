"""
PageRank-style rerank combining query similarity and entity co-occurrence graph.
"""

import math
from typing import Any

from app.core.config import settings
from app.rag.kg.loading.processor import DocumentProcessor
from app.rag.kg.repository import EventRepository, get_session
from app.rag.kg.search.config import SearchConfig
from app.rag.kg.search.ranking.features import (
    base_event_extras,
    clamped_hop,
    event_id,
    event_search_text,
    exact_phrase_metadata,
    kg_path_metadata,
    phrase_score,
    shared_key_entity_count,
)
from app.rag.kg.search.utils import cosine_similarity, format_events


def _key_weight_map(key_final: list[dict[str, Any]]) -> dict[Any, Any]:
    return {item.get("entity_id"): item.get("weight", 0.0) for item in key_final}


def _key_entity_ids(key_final: list[dict[str, Any]]) -> set[str]:
    return {str(item.get("entity_id") or "").strip() for item in key_final or [] if item.get("entity_id")}


def _entity_weight(entity_id_value: str, key_weights: dict[Any, Any], default: float = 0.1) -> float:
    return float(key_weights.get(entity_id_value, default) or default)


def _entity_to_events(assoc_map: dict[str, list[Any]], graph_ids: set[str]) -> dict[str, list[str]]:
    entity_to_events: dict[str, list[str]] = {}
    for item_id, entities in (assoc_map or {}).items():
        if item_id not in graph_ids:
            continue
        for entity in entities or []:
            entity_id_value = str(getattr(entity, "id", "") or "")
            if entity_id_value:
                entity_to_events.setdefault(entity_id_value, []).append(item_id)
    return entity_to_events


def _build_shared_entity_graph(
    *,
    events: list[Any],
    assoc_map: dict[str, list[Any]],
    key_weights: dict[Any, Any],
) -> dict[str, dict[str, float]]:
    graph: dict[str, dict[str, float]] = {event_id(event): {} for event in events}
    graph_ids = set(graph)
    ordered_entities = sorted(
        _entity_to_events(assoc_map, graph_ids).items(),
        key=lambda item: (-_entity_weight(item[0], key_weights), item[0]),
    )
    for entity_id_value, event_list in ordered_entities:
        if len(event_list) < 2:
            continue
        weight = _entity_weight(entity_id_value, key_weights)
        unique_events = sorted(set(event_list))
        for index, left in enumerate(unique_events):
            for right in unique_events[index + 1 :]:
                graph[left][right] = float(graph[left].get(right, 0.0) or 0.0) + weight
                graph[right][left] = float(graph[right].get(left, 0.0) or 0.0) + weight
    return graph


def _base_scores(
    *,
    events: list[Any],
    event_scores: dict[str, float],
    query_vec: list[float],
    assoc_map: dict[str, list[Any]],
    key_weights: dict[Any, Any],
    query: str,
    phrase_boost_weight: float,
) -> dict[str, float]:
    scores: dict[str, float] = {**event_scores}
    for event in events:
        item_id = event_id(event)
        similarity = cosine_similarity(query_vec, getattr(event, "content_vector", None) or [])
        entities = assoc_map.get(item_id, [])
        boost = sum(key_weights.get(str(getattr(entity, "id", "") or ""), 0.0) for entity in entities)
        phrase_boost = phrase_score(query, event_search_text(event)) * phrase_boost_weight
        recall_score = event_scores.get(item_id, 0.0)
        scores[item_id] = 0.5 * recall_score + 0.3 * similarity + 0.2 * boost + phrase_boost
    return scores


def _extras_by_event(
    *,
    events: list[Any],
    assoc_map: dict[str, list[Any]],
    key_entity_ids: set[str],
    event_hops: dict[str, int] | None,
    query: str,
) -> dict[str, dict[str, Any]]:
    extras: dict[str, dict[str, Any]] = {}
    for event in events:
        item_id = event_id(event)
        if not item_id:
            continue
        entities = assoc_map.get(item_id, []) if isinstance(assoc_map, dict) else []
        extra = base_event_extras(
            event,
            hop=clamped_hop(event_hops, item_id),
            shared=shared_key_entity_count(entities, key_entity_ids),
        )
        extra.update(exact_phrase_metadata(query, event))
        extra.update(kg_path_metadata(entities, key_entity_ids))
        extras[item_id] = extra
    return extras


def _outbound_weight_sums(graph: dict[str, dict[str, float]], nodes: list[str]) -> dict[str, float]:
    return {node: float(sum(graph.get(node, {}).values()) or 1.0) for node in nodes}


def _teleport_scores(damping: float, base_scores: dict[str, float], nodes: list[str]) -> dict[str, float]:
    return {node: (1.0 - float(damping)) * float(base_scores.get(node, 0.0) or 0.0) for node in nodes}


def _apply_pagerank_edges(
    *,
    new_scores: dict[str, float],
    edges: dict[str, float],
    scale: float,
) -> None:
    for destination, weight in edges.items():
        current = float(new_scores.get(destination, 0.0) or 0.0)
        new_scores[destination] = current + scale * float(weight or 0.0)


def _pagerank_iteration(
    *,
    nodes: list[str],
    graph: dict[str, dict[str, float]],
    scores: dict[str, float],
    out_sum: dict[str, float],
    teleport: dict[str, float],
    damping: float,
) -> dict[str, float]:
    new_scores = dict(teleport)
    for source in nodes:
        edges = graph.get(source) or {}
        if not edges:
            continue
        denominator = float(out_sum.get(source, 1.0) or 1.0)
        if math.isclose(denominator, 0.0, abs_tol=1e-12):
            continue
        scale = float(damping) * (float(scores.get(source, 0.0) or 0.0) / denominator)
        _apply_pagerank_edges(new_scores=new_scores, edges=edges, scale=scale)
    return new_scores


class RerankPageRankSearcher:
    def __init__(self):
        self.processor = DocumentProcessor()

    async def rerank(
        self,
        config: SearchConfig,
        event_ids: list[str],
        key_final: list[dict[str, Any]],
        event_scores: dict[str, float],
        *,
        query_vector: list[float] | None = None,
        event_hops: dict[str, int] | None = None,
    ) -> dict[str, Any]:
        session = get_session()
        try:
            repo = EventRepository(session)
            events = repo.get_events_by_ids(
                event_ids,
                tenant_id=config.tenant_id,
                document_ids=config.document_ids,
                dataset_id=config.dataset_id,
                account_id=config.account_id,
            )
            if not events:
                return {"events": [], "clues": [], "stats": {}}

            query_vec = (
                query_vector if query_vector is not None else await self.processor.generate_embedding(config.query)
            )
            key_weights = _key_weight_map(key_final)
            key_entity_ids = _key_entity_ids(key_final)
            assoc_map = repo.get_entities_for_events(event_ids, tenant_id=config.tenant_id)
            phrase_boost_weight = max(0.0, float(getattr(settings, "KG_SEARCH_EXACT_PHRASE_RERANK_BOOST", 0.25) or 0.0))
            base_scores = _base_scores(
                events=events,
                event_scores=event_scores,
                query_vec=query_vec,
                assoc_map=assoc_map,
                key_weights=key_weights,
                query=config.query,
                phrase_boost_weight=phrase_boost_weight,
            )
            graph = _build_shared_entity_graph(events=events, assoc_map=assoc_map, key_weights=key_weights)
            scores = self._pagerank(
                graph,
                damping=config.rerank.pagerank_damping_factor,
                max_iter=config.rerank.pagerank_max_iterations,
                base_scores=base_scores,
            )
            extras = _extras_by_event(
                events=events,
                assoc_map=assoc_map,
                key_entity_ids=key_entity_ids,
                event_hops=event_hops,
                query=config.query,
            )

            results = format_events(events, scores, config.rerank.max_results, extra_by_event_id=extras)

            return {
                "events": results,
                "clues": [],
                "stats": {"total_candidates": len(events), "returned": len(results)},
            }
        finally:
            session.close()

    def _pagerank(
        self,
        graph: dict[str, dict[str, float]],
        damping: float,
        max_iter: int,
        base_scores: dict[str, float],
    ) -> dict[str, float]:
        nodes = list(graph.keys())
        if not nodes:
            return {}
        scores = dict.fromkeys(nodes, 1.0)
        out_sum = _outbound_weight_sums(graph, nodes)
        teleport = _teleport_scores(damping, base_scores, nodes)

        for _ in range(int(max_iter)):
            scores = _pagerank_iteration(
                nodes=nodes,
                graph=graph,
                scores=scores,
                out_sum=out_sum,
                teleport=teleport,
                damping=damping,
            )
        return scores

from typing import Any


def _positive_weight(value: Any) -> float | None:
    try:
        weight = float(value)
    except (TypeError, ValueError):
        return None
    return weight if weight > 0.0 else None


def _normalized_edges(src_id: str, edges: dict[str, float] | None) -> dict[str, float]:
    out: dict[str, float] = {}
    for dst, weight in (edges or {}).items():
        dst_id = str(dst or "").strip()
        edge_weight = _positive_weight(weight)
        if dst_id and dst_id != src_id and edge_weight is not None:
            out[dst_id] = edge_weight
    return out


def _normalize_graph(graph: dict[str, dict[str, float]] | None) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for src, edges in (graph or {}).items():
        src_id = str(src or "").strip()
        if src_id:
            out[src_id] = _normalized_edges(src_id, edges)
    return out


def _graph_nodes(normalized_graph: dict[str, dict[str, float]], seed_weights: dict[str, float]) -> list[str]:
    seed_nodes = {str(key).strip() for key in (seed_weights or {}) if str(key).strip()}
    return sorted(set(normalized_graph.keys()) | seed_nodes)


def _personalization_raw(nodes: list[str], seed_weights: dict[str, float]) -> dict[str, float]:
    raw: dict[str, float] = {}
    for node in nodes:
        raw[node] = max(0.0, _positive_weight((seed_weights or {}).get(node, 0.0)) or 0.0)
    return raw


def _normalize_personalization(nodes: list[str], personalization_raw: dict[str, float]) -> dict[str, float]:
    total_seed = sum(personalization_raw.values())
    if total_seed <= 0.0:
        return {node: 1.0 / float(len(nodes)) for node in nodes}
    return {node: float(weight) / float(total_seed) for node, weight in personalization_raw.items()}


def _run_power_iterations(
    *,
    nodes: list[str],
    graph: dict[str, dict[str, float]],
    personalization: dict[str, float],
    damping: float,
    max_iter: int,
) -> dict[str, float]:
    scores = {node: personalization.get(node, 0.0) for node in nodes}
    out_sum = {node: sum((graph.get(node) or {}).values()) or 1.0 for node in nodes}
    damping_value = float(damping)
    for _ in range(max(1, int(max_iter or 1))):
        next_scores = {node: (1.0 - damping_value) * personalization.get(node, 0.0) for node in nodes}
        for src in nodes:
            src_score = float(scores.get(src, 0.0) or 0.0)
            denom = float(out_sum.get(src, 1.0) or 1.0)
            for dst, weight in (graph.get(src) or {}).items():
                next_scores[dst] = float(next_scores.get(dst, 0.0) or 0.0) + damping_value * src_score * (
                    float(weight) / denom
                )
        scores = next_scores
    return scores


def _blended_rankings(
    *,
    nodes: list[str],
    scores: dict[str, float],
    personalization: dict[str, float],
) -> list[tuple[str, float]]:
    blended_scores = {
        node: (0.7 * float(scores.get(node, 0.0) or 0.0)) + (0.3 * float(personalization.get(node, 0.0) or 0.0))
        for node in nodes
    }
    return sorted(blended_scores.items(), key=lambda item: (-float(item[1]), item[0]))


def _seed_nodes(personalization_raw: dict[str, float]) -> list[str]:
    return [
        node
        for node, weight in sorted(personalization_raw.items(), key=lambda item: (-item[1], item[0]))
        if weight > 0.0
    ]


def rank_personalized_graph(
    *,
    graph: dict[str, dict[str, float]],
    seed_weights: dict[str, float],
    top_k: int = 10,
    damping: float = 0.85,
    max_iter: int = 50,
) -> dict[str, Any]:
    normalized_graph = _normalize_graph(graph)
    nodes = _graph_nodes(normalized_graph, seed_weights)
    if not nodes:
        return {"schema": "mimirq.kg_pprank.v1", "seed_nodes": [], "results": []}

    personalization_raw = _personalization_raw(nodes, seed_weights)
    personalization = _normalize_personalization(nodes, personalization_raw)
    scores = _run_power_iterations(
        nodes=nodes,
        graph=normalized_graph,
        personalization=personalization,
        damping=damping,
        max_iter=max_iter,
    )
    ranked = _blended_rankings(nodes=nodes, scores=scores, personalization=personalization)
    limit = max(0, int(top_k or 0)) or len(ranked)
    return {
        "schema": "mimirq.kg_pprank.v1",
        "seed_nodes": _seed_nodes(personalization_raw),
        "results": [{"node_id": node, "score": round(float(score), 4)} for node, score in ranked[:limit]],
    }


__all__ = ["rank_personalized_graph"]

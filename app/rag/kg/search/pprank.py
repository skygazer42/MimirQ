from __future__ import annotations

from typing import Any


def _normalize_graph(graph: dict[str, dict[str, float]] | None) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for src, edges in (graph or {}).items():
        src_id = str(src or "").strip()
        if not src_id:
            continue
        out[src_id] = {}
        for dst, weight in (edges or {}).items():
            dst_id = str(dst or "").strip()
            if not dst_id or dst_id == src_id:
                continue
            try:
                w = float(weight)
            except (TypeError, ValueError):
                continue
            if w <= 0.0:
                continue
            out[src_id][dst_id] = float(w)
    return out


def rank_personalized_graph(
    *,
    graph: dict[str, dict[str, float]],
    seed_weights: dict[str, float],
    top_k: int = 10,
    damping: float = 0.85,
    max_iter: int = 50,
) -> dict[str, Any]:
    normalized_graph = _normalize_graph(graph)
    nodes = sorted(set(normalized_graph.keys()) | {str(k).strip() for k in (seed_weights or {}) if str(k).strip()})
    if not nodes:
        return {"schema": "mimirq.kg_pprank.v1", "seed_nodes": [], "results": []}

    personalization_raw: dict[str, float] = {}
    for node in nodes:
        try:
            personalization_raw[node] = max(0.0, float((seed_weights or {}).get(node, 0.0) or 0.0))
        except (TypeError, ValueError):
            personalization_raw[node] = 0.0
    total_seed = sum(personalization_raw.values())
    if total_seed <= 0.0:
        personalization = {node: 1.0 / float(len(nodes)) for node in nodes}
    else:
        personalization = {node: float(weight) / float(total_seed) for node, weight in personalization_raw.items()}

    scores = {node: personalization.get(node, 0.0) for node in nodes}
    out_sum = {node: sum((normalized_graph.get(node) or {}).values()) or 1.0 for node in nodes}

    for _ in range(max(1, int(max_iter or 1))):
        next_scores = {node: (1.0 - float(damping)) * personalization.get(node, 0.0) for node in nodes}
        for src in nodes:
            src_score = float(scores.get(src, 0.0) or 0.0)
            edges = normalized_graph.get(src) or {}
            denom = float(out_sum.get(src, 1.0) or 1.0)
            for dst, weight in edges.items():
                next_scores[dst] = float(next_scores.get(dst, 0.0) or 0.0) + float(damping) * src_score * (float(weight) / denom)
        scores = next_scores

    blended_scores = {
        node: (0.7 * float(scores.get(node, 0.0) or 0.0)) + (0.3 * float(personalization.get(node, 0.0) or 0.0))
        for node in nodes
    }
    ranked = sorted(blended_scores.items(), key=lambda item: (-float(item[1]), item[0]))
    limit = max(0, int(top_k or 0)) or len(ranked)
    return {
        "schema": "mimirq.kg_pprank.v1",
        "seed_nodes": [node for node, weight in sorted(personalization_raw.items(), key=lambda item: (-item[1], item[0])) if weight > 0.0],
        "results": [{"node_id": node, "score": round(float(score), 4)} for node, score in ranked[:limit]],
    }


__all__ = ["rank_personalized_graph"]

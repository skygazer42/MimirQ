from collections import defaultdict, deque
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.api.dependencies.auth import get_current_account_id
from app.rag.kg.community import CommunityEdge, label_propagation_communities

_DEFAULT_HTTP_EXCEPTION_RESPONSES = {
    400: {"description": "Bad Request"},
    403: {"description": "Forbidden"},
    404: {"description": "Not Found"},
    409: {"description": "Conflict"},
    416: {"description": "Range Not Satisfiable"},
}

# These endpoints run graph algorithms over a client-supplied edge list and never
# touch tenant data, but they must still require authentication (parity with the
# rest of /api/v1, which enforces auth per-route rather than via global middleware)
# so they cannot be abused as an unauthenticated compute/DoS surface.
router = APIRouter(
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
    dependencies=[Depends(get_current_account_id)],
)
_SCHEMA = "mimirq.kg_network_analysis.v1"

# Upper bound on the client-supplied edge list. Path enumeration / PageRank over an
# unbounded graph is a CPU/memory DoS vector, so cap the input size defensively.
_MAX_EDGES = 20_000


class EdgeIn(BaseModel):
    source: str
    target: str
    weight: float = 1.0


class GraphRequest(BaseModel):
    edges: list[EdgeIn] = Field(default_factory=list, max_length=_MAX_EDGES)
    start_id: str | None = None
    target_id: str | None = None
    max_hops: int = Field(default=2, ge=1, le=10)
    top_k: int = Field(default=10, ge=1, le=100)
    algorithm: Literal["degree", "pagerank"] = "degree"
    node_id: str | None = None


def _adjacency(edges: list[EdgeIn]) -> dict[str, dict[str, float]]:
    graph: dict[str, dict[str, float]] = defaultdict(dict)
    for edge in edges:
        source = str(edge.source or "").strip()
        target = str(edge.target or "").strip()
        if not source or not target or source == target:
            continue
        weight = float(edge.weight or 1.0)
        graph[source][target] = max(float(graph[source].get(target, 0.0) or 0.0), weight)
        graph[target][source] = max(float(graph[target].get(source, 0.0) or 0.0), weight)
    return dict(graph)


def _k_hop_neighbors(graph: dict[str, dict[str, float]], *, start_id: str, max_hops: int) -> list[dict[str, int | str]]:
    seen = {start_id}
    q: deque[tuple[str, int]] = deque([(start_id, 0)])
    out: list[dict[str, int | str]] = []
    while q:
        node, hop = q.popleft()
        if hop >= max_hops:
            continue
        for neighbor in sorted((graph.get(node) or {}).keys()):
            if neighbor in seen:
                continue
            seen.add(neighbor)
            next_hop = hop + 1
            out.append({"node_id": neighbor, "hop": next_hop})
            q.append((neighbor, next_hop))
    return out


def _shortest_path(graph: dict[str, dict[str, float]], *, start_id: str, target_id: str) -> list[str]:
    q: deque[list[str]] = deque([[start_id]])
    seen = {start_id}
    while q:
        path = q.popleft()
        node = path[-1]
        if node == target_id:
            return path
        for neighbor in sorted((graph.get(node) or {}).keys()):
            if neighbor in seen:
                continue
            seen.add(neighbor)
            q.append(path + [neighbor])
    return []


def _all_paths_between(
    graph: dict[str, dict[str, float]], *, start_id: str, target_id: str, max_hops: int
) -> list[list[str]]:
    out: list[list[str]] = []

    def _dfs(path: list[str]) -> None:
        node = path[-1]
        if len(path) - 1 > max_hops:
            return
        if node == target_id and len(path) > 1:
            out.append(list(path))
            return
        for neighbor in sorted((graph.get(node) or {}).keys()):
            if neighbor in path:
                continue
            _dfs(path + [neighbor])

    _dfs([start_id])
    return out


def _degree_centrality(graph: dict[str, dict[str, float]]) -> list[dict[str, float | str]]:
    rows = [{"node_id": node, "score": float(len(neighbors))} for node, neighbors in graph.items()]
    rows.sort(key=lambda row: (-float(row["score"]), str(row["node_id"])))
    return rows


def _pagerank(
    graph: dict[str, dict[str, float]], *, damping: float = 0.85, max_iter: int = 40
) -> list[dict[str, float | str]]:
    nodes = sorted(graph.keys())
    if not nodes:
        return []
    scores = {node: 1.0 / float(len(nodes)) for node in nodes}
    for _ in range(max_iter):
        next_scores = {node: (1.0 - damping) / float(len(nodes)) for node in nodes}
        for src in nodes:
            edges = graph.get(src) or {}
            denom = sum(edges.values()) or 1.0
            for dst, weight in edges.items():
                next_scores[dst] += damping * scores[src] * (float(weight) / float(denom))
        scores = next_scores
    rows = [{"node_id": node, "score": round(float(scores[node]), 4)} for node in nodes]
    rows.sort(key=lambda row: (-float(row["score"]), str(row["node_id"])))
    return rows


@router.post("/k_hop_neighbors")
def k_hop_neighbors(body: GraphRequest) -> dict:
    graph = _adjacency(body.edges)
    start = str(body.start_id or "").strip()
    return {
        "schema": _SCHEMA,
        "neighbors": _k_hop_neighbors(graph, start_id=start, max_hops=int(body.max_hops)),
    }


@router.post("/shortest_path")
def shortest_path(body: GraphRequest) -> dict:
    graph = _adjacency(body.edges)
    start = str(body.start_id or "").strip()
    target = str(body.target_id or "").strip()
    path = _shortest_path(graph, start_id=start, target_id=target)
    return {
        "schema": _SCHEMA,
        "path": path,
        "path_length": max(0, len(path) - 1),
    }


@router.post("/paths_between")
def paths_between(body: GraphRequest) -> dict:
    graph = _adjacency(body.edges)
    start = str(body.start_id or "").strip()
    target = str(body.target_id or "").strip()
    paths = _all_paths_between(graph, start_id=start, target_id=target, max_hops=int(body.max_hops))
    return {"schema": _SCHEMA, "paths": paths}


@router.post("/centrality")
def centrality(body: GraphRequest) -> dict:
    graph = _adjacency(body.edges)
    rows = _degree_centrality(graph) if body.algorithm == "degree" else _pagerank(graph)
    return {
        "schema": _SCHEMA,
        "metric": body.algorithm,
        "scores": rows[: int(body.top_k)],
    }


@router.post("/community_of")
def community_of(body: GraphRequest) -> dict:
    graph = _adjacency(body.edges)
    nodes = sorted(graph.keys())
    edges = [
        CommunityEdge(a=src, b=dst, w=weight)
        for src, neighbors in graph.items()
        for dst, weight in neighbors.items()
        if src < dst
    ]
    labels = label_propagation_communities(nodes=nodes, edges=edges, max_iters=20)
    return {
        "schema": _SCHEMA,
        "node_id": body.node_id,
        "community_id": labels.get(str(body.node_id or "").strip()),
    }


@router.post("/connected_component")
def connected_component(body: GraphRequest) -> dict:
    graph = _adjacency(body.edges)
    start = str(body.start_id or "").strip()
    component = [start]
    seen = {start}
    q: deque[str] = deque([start])
    while q:
        node = q.popleft()
        for neighbor in sorted((graph.get(node) or {}).keys()):
            if neighbor in seen:
                continue
            seen.add(neighbor)
            component.append(neighbor)
            q.append(neighbor)
    return {"schema": _SCHEMA, "component": component}


__all__ = ["router"]

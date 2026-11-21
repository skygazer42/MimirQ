from collections import defaultdict, deque
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.api.dependencies import get_current_account_id
from app.api.utils import DEFAULT_HTTP_EXCEPTION_RESPONSES as _DEFAULT_HTTP_EXCEPTION_RESPONSES
from app.rag.kg.community import CommunityEdge, label_propagation_communities

# Client-supplied graphs do not read tenant data, but these compute endpoints
# still require authentication like the rest of /api/v1.
router = APIRouter(
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
    dependencies=[Depends(get_current_account_id)],
)
_SCHEMA = "mimirq.kg_network_analysis.v1"

# Bound request size; this does not bound the number of simple paths.
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


class _NetworkResponse(BaseModel):
    schema_: Literal["mimirq.kg_network_analysis.v1"] = Field(default=_SCHEMA, alias="schema")


class Neighbor(BaseModel):
    node_id: str
    hop: int


class KHopNeighborsResponse(_NetworkResponse):
    neighbors: list[Neighbor]


class ShortestPathResponse(_NetworkResponse):
    path: list[str]
    path_length: int


class PathsBetweenResponse(_NetworkResponse):
    paths: list[list[str]]


class CentralityScore(BaseModel):
    node_id: str
    score: float


class CentralityResponse(_NetworkResponse):
    metric: Literal["degree", "pagerank"]
    scores: list[CentralityScore]


class CommunityResponse(_NetworkResponse):
    node_id: str | None
    community_id: str | None


class ConnectedComponentResponse(_NetworkResponse):
    component: list[str]


def _adjacency(edges: list[EdgeIn]) -> dict[str, dict[str, float]]:
    graph: dict[str, dict[str, float]] = defaultdict(dict)
    for edge in edges:
        source = edge.source.strip()
        target = edge.target.strip()
        if not source or not target or source == target:
            continue
        weight = edge.weight
        graph[source][target] = max(graph[source].get(target, 0.0), weight)
        graph[target][source] = max(graph[target].get(source, 0.0), weight)
    return dict(graph)


def _k_hop_neighbors(graph: dict[str, dict[str, float]], *, start_id: str, max_hops: int) -> list[Neighbor]:
    seen = {start_id}
    queue: deque[tuple[str, int]] = deque([(start_id, 0)])
    neighbors: list[Neighbor] = []
    while queue:
        node, hop = queue.popleft()
        if hop >= max_hops:
            continue
        for neighbor in sorted(graph.get(node, {})):
            if neighbor in seen:
                continue
            seen.add(neighbor)
            next_hop = hop + 1
            neighbors.append(Neighbor(node_id=neighbor, hop=next_hop))
            queue.append((neighbor, next_hop))
    return neighbors


def _shortest_path(graph: dict[str, dict[str, float]], *, start_id: str, target_id: str) -> list[str]:
    queue: deque[list[str]] = deque([[start_id]])
    seen = {start_id}
    while queue:
        path = queue.popleft()
        node = path[-1]
        if node == target_id:
            return path
        for neighbor in sorted(graph.get(node, {})):
            if neighbor in seen:
                continue
            seen.add(neighbor)
            queue.append(path + [neighbor])
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
        for neighbor in sorted(graph.get(node, {})):
            if neighbor in path:
                continue
            _dfs(path + [neighbor])

    _dfs([start_id])
    return out


def _degree_centrality(graph: dict[str, dict[str, float]]) -> list[CentralityScore]:
    rows = [CentralityScore(node_id=node, score=len(neighbors)) for node, neighbors in graph.items()]
    rows.sort(key=lambda row: (-row.score, row.node_id))
    return rows


def _pagerank(
    graph: dict[str, dict[str, float]], *, damping: float = 0.85, max_iter: int = 40
) -> list[CentralityScore]:
    nodes = sorted(graph)
    if not nodes:
        return []
    scores = {node: 1.0 / len(nodes) for node in nodes}
    for _ in range(max_iter):
        next_scores = {node: (1.0 - damping) / len(nodes) for node in nodes}
        for src in nodes:
            edges = graph[src]
            denom = sum(edges.values()) or 1.0
            for dst, weight in edges.items():
                next_scores[dst] += damping * scores[src] * (weight / denom)
        scores = next_scores
    rows = [CentralityScore(node_id=node, score=round(scores[node], 4)) for node in nodes]
    rows.sort(key=lambda row: (-row.score, row.node_id))
    return rows


@router.post("/k_hop_neighbors")
def k_hop_neighbors(body: GraphRequest) -> KHopNeighborsResponse:
    graph = _adjacency(body.edges)
    start = body.start_id.strip() if body.start_id is not None else None
    neighbors = [] if not start else _k_hop_neighbors(graph, start_id=start, max_hops=body.max_hops)
    return KHopNeighborsResponse(neighbors=neighbors)


@router.post("/shortest_path")
def shortest_path(body: GraphRequest) -> ShortestPathResponse:
    graph = _adjacency(body.edges)
    start = body.start_id.strip() if body.start_id is not None else None
    target = body.target_id.strip() if body.target_id is not None else None
    if not start or not target:
        return ShortestPathResponse(path=[], path_length=0)
    path = _shortest_path(graph, start_id=start, target_id=target)
    return ShortestPathResponse(path=path, path_length=max(0, len(path) - 1))


@router.post("/paths_between")
def paths_between(body: GraphRequest) -> PathsBetweenResponse:
    graph = _adjacency(body.edges)
    start = body.start_id.strip() if body.start_id is not None else None
    target = body.target_id.strip() if body.target_id is not None else None
    if not start or not target:
        return PathsBetweenResponse(paths=[])
    paths = _all_paths_between(graph, start_id=start, target_id=target, max_hops=body.max_hops)
    return PathsBetweenResponse(paths=paths)


@router.post("/centrality")
def centrality(body: GraphRequest) -> CentralityResponse:
    graph = _adjacency(body.edges)
    rows = _degree_centrality(graph) if body.algorithm == "degree" else _pagerank(graph)
    return CentralityResponse(metric=body.algorithm, scores=rows[: body.top_k])


@router.post("/community_of")
def community_of(body: GraphRequest) -> CommunityResponse:
    graph = _adjacency(body.edges)
    nodes = sorted(graph)
    edges = [
        CommunityEdge(a=src, b=dst, w=weight)
        for src, neighbors in graph.items()
        for dst, weight in neighbors.items()
        if src < dst
    ]
    labels = label_propagation_communities(nodes=nodes, edges=edges, max_iters=20)
    node_id = body.node_id.strip() if body.node_id is not None else None
    return CommunityResponse(node_id=body.node_id, community_id=labels.get(node_id))


@router.post("/connected_component")
def connected_component(body: GraphRequest) -> ConnectedComponentResponse:
    graph = _adjacency(body.edges)
    start = body.start_id.strip() if body.start_id is not None else None
    if not start:
        return ConnectedComponentResponse(component=[])
    component = [start]
    seen = {start}
    queue: deque[str] = deque([start])
    while queue:
        node = queue.popleft()
        for neighbor in sorted(graph.get(node, {})):
            if neighbor in seen:
                continue
            seen.add(neighbor)
            component.append(neighbor)
            queue.append(neighbor)
    return ConnectedComponentResponse(component=component)


__all__ = ["router"]

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient


def _app():
    from app.api.v1.network_analysis import router

    app = FastAPI()
    app.include_router(router, prefix="/api/v1/kg/network")
    return app


def test_network_analysis_router_is_included_in_api_v1() -> None:
    import langchain

    if not hasattr(langchain, "debug"):
        langchain.debug = False
    if not hasattr(langchain, "verbose"):
        langchain.verbose = False
    if not hasattr(langchain, "llm_cache"):
        langchain.llm_cache = None

    from app.api.v1 import get_router

    router = get_router()
    paths = {route.path for route in router.routes}
    assert "/kg/network/k_hop_neighbors" in paths
    assert "/kg/network/shortest_path" in paths


def test_k_hop_neighbors_endpoint_returns_neighbor_layers() -> None:
    client = TestClient(_app())
    res = client.post(
        "/api/v1/kg/network/k_hop_neighbors",
        json={
            "edges": [
                {"source": "A", "target": "B"},
                {"source": "B", "target": "C"},
                {"source": "C", "target": "D"},
            ],
            "start_id": "A",
            "max_hops": 2,
        },
    )

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["schema"] == "mimirq.kg_network_analysis.v1"
    assert body["neighbors"] == [
        {"node_id": "B", "hop": 1},
        {"node_id": "C", "hop": 2},
    ]


def test_shortest_path_endpoint_returns_path() -> None:
    client = TestClient(_app())
    res = client.post(
        "/api/v1/kg/network/shortest_path",
        json={
            "edges": [
                {"source": "A", "target": "B"},
                {"source": "B", "target": "C"},
                {"source": "A", "target": "D"},
                {"source": "D", "target": "C"},
            ],
            "start_id": "A",
            "target_id": "C",
        },
    )

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["path"] in (["A", "B", "C"], ["A", "D", "C"])
    assert body["path_length"] == 2


def test_centrality_endpoint_returns_degree_and_pagerank_scores() -> None:
    client = TestClient(_app())
    res = client.post(
        "/api/v1/kg/network/centrality",
        json={
            "edges": [
                {"source": "A", "target": "B"},
                {"source": "B", "target": "C"},
                {"source": "B", "target": "D"},
            ],
            "algorithm": "degree",
        },
    )

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["metric"] == "degree"
    assert body["scores"][0]["node_id"] == "B"
    assert body["scores"][0]["score"] == 3.0

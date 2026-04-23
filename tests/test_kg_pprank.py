from __future__ import annotations

from app.rag.kg.search.pprank import rank_personalized_graph


def test_rank_personalized_graph_prioritizes_seed_neighborhood() -> None:
    out = rank_personalized_graph(
        graph={
            "A": {"B": 1.0},
            "B": {"A": 1.0, "C": 1.0},
            "C": {"B": 1.0},
        },
        seed_weights={"A": 1.0},
        top_k=3,
    )

    assert out["schema"] == "mimirq.kg_pprank.v1"
    assert [row["node_id"] for row in out["results"]] == ["A", "B", "C"]
    assert out["results"][0]["score"] >= out["results"][1]["score"] >= out["results"][2]["score"]
    assert out["seed_nodes"] == ["A"]


def test_rank_personalized_graph_merges_multiple_seed_weights() -> None:
    out = rank_personalized_graph(
        graph={
            "A": {"B": 1.0},
            "B": {"A": 1.0, "C": 1.0},
            "C": {"B": 1.0, "D": 1.0},
            "D": {"C": 1.0},
        },
        seed_weights={"A": 0.4, "D": 0.6},
        top_k=2,
    )

    assert out["results"][0]["node_id"] == "D"
    assert out["results"][1]["node_id"] in {"A", "C"}
    assert out["results"][0]["score"] > 0.0

from __future__ import annotations


def test_walkhash_graph_embeddings_are_deterministic_and_rank_neighbors() -> None:
    from app.rag.kg.search import graph_embeddings as ge

    class _Link:
        def __init__(self, entity_id: str) -> None:
            self.entity_id = entity_id

    # Build a tiny bipartite graph:
    # - A and B co-occur in multiple events (strong tie)
    # - C only connects via B (weaker tie to A)
    event_entity_links = {
        "X1": [_Link("A"), _Link("B")],
        "X2": [_Link("A"), _Link("B")],
        "X3": [_Link("A"), _Link("B")],
        "Y": [_Link("B"), _Link("C")],
    }

    adjacency = ge.build_entity_event_adjacency(
        seed_entity_ids=["A"],
        event_ids=["X1", "X2", "X3", "Y"],
        event_entity_links=event_entity_links,
        kept_entity_ids={"A", "B", "C"},
        relation_edges=None,
    )

    params = ge.WalkHashParams(dim=32, num_walks=16, walk_length=12, window_size=3, seed=7)

    hits1 = ge.recall_similar_entity_nodes(
        adjacency=adjacency,
        seed_entity_node_keys=["ent:A"],
        params=params,
        top_k=5,
        min_similarity=0.0,
        entity_prefix="ent:",
    )
    hits2 = ge.recall_similar_entity_nodes(
        adjacency=adjacency,
        seed_entity_node_keys=["ent:A"],
        params=params,
        top_k=5,
        min_similarity=0.0,
        entity_prefix="ent:",
    )

    assert hits1 == hits2, "graph embeddings should be deterministic for fixed seed/graph"
    assert hits1, "expected at least one similar entity"
    assert hits1[0]["node_key"] == "ent:B"
    assert hits1[0]["seed_node_key"] == "ent:A"

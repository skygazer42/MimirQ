from __future__ import annotations

from app.rag.kg.quality.kg_completeness_scorer import _connectivity_metrics


def test_connectivity_metrics_counts_components() -> None:
    nodes = {"a", "b", "c", "d"}
    edges = [("a", "b"), ("b", "c")]
    metrics = _connectivity_metrics(nodes=nodes, edges=edges)
    assert metrics["nodes"] == 4
    assert metrics["edges"] == 2
    assert metrics["components"] == 2
    assert metrics["largest_component_size"] == 3


from __future__ import annotations

from app.rag.evaluation.metrics.routing import compute_routing_accuracy


def test_compute_routing_accuracy_ignores_samples_without_expected_route() -> None:
    accuracy = compute_routing_accuracy(
        [
            {"expected_route": "retrieval", "actual_route": "retrieval"},
            {"expected_route": None, "actual_route": "kg"},
            {"expected_route": "kg", "actual_route": "hybrid"},
        ]
    )

    assert accuracy["evaluated"] == 2
    assert accuracy["correct"] == 1
    assert accuracy["routing_accuracy"] == 0.5

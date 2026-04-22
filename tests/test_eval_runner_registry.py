from __future__ import annotations

from app.rag.evaluation.runners.registry import get_registered_route_ids


def test_runner_registry_exposes_three_active_routes_and_agentic_placeholder() -> None:
    routes = get_registered_route_ids()

    assert routes == ["retrieval", "kg", "hybrid", "agentic"]

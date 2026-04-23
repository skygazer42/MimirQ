from __future__ import annotations

from app.rag.kg.search.plan_on_graph import build_plan_on_graph


def test_build_plan_on_graph_emits_subgoals_and_memory_state() -> None:
    out = build_plan_on_graph(
        query="Why did the 485 bus fail after the watchdog alarm?",
        topic_entities=["485 bus", "watchdog"],
        explored_entities=["alarm-log"],
    )

    assert out["schema"] == "mimirq.kg_plan_on_graph.v1"
    assert out["subgoals"] == [
        "Locate evidence about 485 bus.",
        "Locate evidence about watchdog.",
        "Connect the subgraph evidence into one explanation.",
    ]
    assert out["memory"]["explored_entities"] == ["alarm-log"]
    assert out["next_action"] == "expand_subgraph"


def test_build_plan_on_graph_requests_reflection_when_no_entities_are_available() -> None:
    out = build_plan_on_graph(
        query="Compare cross-region drift in supplier risk.",
        topic_entities=[],
        explored_entities=[],
    )

    assert out["subgoals"] == ["Clarify missing graph anchors from the query."]
    assert out["reflection"]["needed"] is True
    assert out["next_action"] == "reseed_entities"

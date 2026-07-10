
from typing import Any


def build_plan_on_graph(
    *,
    query: str,
    topic_entities: list[str],
    explored_entities: list[str] | None = None,
) -> dict[str, Any]:
    entities = [str(item or "").strip() for item in topic_entities or [] if str(item or "").strip()]
    explored = [str(item or "").strip() for item in explored_entities or [] if str(item or "").strip()]

    if not entities:
        return {
            "schema": "mimirq.kg_plan_on_graph.v1",
            "query": str(query or "").strip(),
            "subgoals": ["Clarify missing graph anchors from the query."],
            "memory": {"explored_entities": explored},
            "reflection": {"needed": True, "reason_codes": ["missing_topic_entities"]},
            "next_action": "reseed_entities",
        }

    subgoals = [f"Locate evidence about {entity}." for entity in entities[:2]]
    subgoals.append("Connect the subgraph evidence into one explanation.")
    return {
        "schema": "mimirq.kg_plan_on_graph.v1",
        "query": str(query or "").strip(),
        "subgoals": subgoals,
        "memory": {"explored_entities": explored},
        "reflection": {"needed": False, "reason_codes": []},
        "next_action": "expand_subgraph",
    }


__all__ = ["build_plan_on_graph"]

from __future__ import annotations

import pytest


def test_label_propagation_communities_is_deterministic_for_disconnected_components() -> None:
    from app.rag.kg.community import CommunityEdge, label_propagation_communities

    nodes = ["A", "B", "C", "D"]
    edges = [
        CommunityEdge(a="A", b="B", w=3.0),
        CommunityEdge(a="C", b="D", w=2.0),
    ]
    out = label_propagation_communities(nodes=nodes, edges=edges, max_iters=10)
    assert out["A"] == "B"
    assert out["B"] == "B"
    assert out["C"] == "D"
    assert out["D"] == "D"


def test_build_community_reports_groups_entities_and_emits_global_summary() -> None:
    from app.rag.kg.community import build_community_reports

    entities = [
        {"entity_id": "A", "name": "Alpha", "type": "Thing", "weight": 0.9},
        {"entity_id": "B", "name": "Beta", "type": "Thing", "weight": 0.8},
        {"entity_id": "C", "name": "Gamma", "type": "Thing", "weight": 0.7},
        {"entity_id": "D", "name": "Delta", "type": "Thing", "weight": 0.6},
    ]
    events = [
        {"id": "e1", "title": "Event One", "summary": "S1", "score": 0.9},
        {"id": "e2", "title": "Event Two", "summary": "S2", "score": 0.8},
    ]
    event_entities = {
        "e1": ["A", "B"],
        "e2": ["C", "D"],
    }

    reports, global_summary = build_community_reports(
        entities=entities,
        events=events,
        event_entities=event_entities,
        max_entities_per_event=10,
        min_edge_weight=1.0,
        label_propagation_iters=10,
        max_communities=10,
        max_entities_per_community=10,
        max_events_per_community=10,
        global_summary_max_chars=5000,
    )

    assert len(reports) == 2
    assert "Found 2 communities" in global_summary
    for rep in reports:
        assert rep.get("schema") == "mimirq.kg_community_report.v1"
        assert rep.get("community_id")
        assert rep.get("entity_count") == 2
        assert rep.get("event_count") == 1
        assert rep.get("entities")
        assert rep.get("events")
        assert rep.get("summary")


@pytest.mark.asyncio
async def test_lazy_summarize_returns_trimmed_llm_text() -> None:
    from app.rag.kg.community import lazy_summarize
    from app.rag.llm.models import LLMResponse

    class _FakeLLM:
        async def chat(self, _messages, **_kwargs):  # noqa: ANN001, ANN003
            return LLMResponse(content="  concise summary  ")

    summary = await lazy_summarize(
        community_report={
            "community_id": "1",
            "entities": [{"name": "Alpha", "type": "Thing"}],
            "events": [{"title": "Event A"}],
        },
        query="What happened with Alpha?",
        llm_client=_FakeLLM(),
        max_tokens=120,
    )

    assert summary == "concise summary"

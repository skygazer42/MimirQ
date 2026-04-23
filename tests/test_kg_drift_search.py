from __future__ import annotations

from app.rag.kg.search.drift_search import run_drift_search


def test_run_drift_search_selects_communities_by_summary_match() -> None:
    out = run_drift_search(
        query="Compare revenue drift across regions",
        community_reports=[
            {
                "community_id": "1",
                "summary": "Revenue trend and regional change analysis.",
                "entities": [{"entity_id": "e1"}],
                "events": [{"id": "ev-1"}],
            },
            {
                "community_id": "2",
                "summary": "Maintenance alarms and PLC watchdog resets.",
                "entities": [{"entity_id": "e2"}],
                "events": [{"id": "ev-2"}],
            },
        ],
        top_k=1,
    )

    assert out["schema"] == "mimirq.kg_drift_search.v1"
    assert out["selected_communities"][0]["community_id"] == "1"
    assert out["expanded_entity_ids"] == ["e1"]
    assert out["expanded_event_ids"] == ["ev-1"]


def test_run_drift_search_falls_back_to_first_community_when_no_overlap() -> None:
    out = run_drift_search(
        query="Unrelated query text",
        community_reports=[
            {"community_id": "1", "summary": "Alpha beta", "entities": [], "events": []},
            {"community_id": "2", "summary": "Gamma delta", "entities": [], "events": []},
        ],
        top_k=1,
    )

    assert out["selected_communities"][0]["community_id"] == "1"
    assert out["reason_codes"] == ["fallback_first_community"]

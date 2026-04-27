from __future__ import annotations

from app.rag.kg.search.path_verbalizer import build_path_renderings


def test_build_path_renderings_emits_all_representations() -> None:
    event = {
        "id": "ev-1",
        "title": "PLC Temperature Alarm",
        "summary": "Alarm triggered after coolant failure.",
        "kg_path": [
            {"entity_id": "e-plc", "type": "Device"},
            {"entity_id": "e-coolant", "type": "Subsystem"},
        ],
    }
    key_entities = [
        {"entity_id": "e-plc", "name": "PLC-7", "type": "Device", "weight": 0.9},
        {"entity_id": "e-coolant", "name": "Cooling Loop", "type": "Subsystem", "weight": 0.8},
    ]
    community_reports = [
        {
            "community_id": "c-1",
            "summary": "Cooling subsystem incidents clustered with PLC alarms.",
        }
    ]

    out = build_path_renderings(
        event=event,
        key_entities=key_entities,
        query="Why did the PLC overheat?",
        community_reports=community_reports,
    )

    assert out["schema"] == "mimirq.kg_path_renderings.v1"
    assert out["path_string"] == "PLC-7 [Device] -> Cooling Loop [Subsystem] -> PLC Temperature Alarm"
    assert len(out["verbalized_triples"]) == 2
    assert "PLC-7" in out["verbalized_triples"][0]
    assert out["graph_prompt"]["nodes"][0]["label"] == "PLC-7"
    assert out["graph_prompt"]["nodes"][-1]["label"] == "PLC Temperature Alarm"
    assert "Why did the PLC overheat?" in out["reasoning_chain"]
    assert "Cooling subsystem incidents" in out["community_context"]

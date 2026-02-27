from __future__ import annotations


def test_diff_kg_snapshots_reports_count_deltas_and_type_deltas() -> None:
    from app.rag.kg.snapshot import diff_kg_snapshots

    a = {
        "schema": "mimirq.kg_snapshot.v1",
        "pipeline_hash": "v1",
        "docs": 10,
        "events": 100,
        "entities": 40,
        "links": 200,
        "relations": 12,
        "entity_types": [
            {"type": "Skill", "count": 20},
            {"type": "Tool", "count": 5},
        ],
    }
    b = {
        "schema": "mimirq.kg_snapshot.v1",
        "pipeline_hash": "v2",
        "docs": 10,
        "events": 90,
        "entities": 55,
        "links": 210,
        "relations": 10,
        "entity_types": [
            {"type": "Skill", "count": 25},
            {"type": "Person", "count": 3},
        ],
    }

    diff = diff_kg_snapshots(a, b)
    assert diff.get("schema") == "mimirq.kg_snapshot_diff.v1"
    assert diff.get("pipeline_hash_a") == "v1"
    assert diff.get("pipeline_hash_b") == "v2"

    delta = diff.get("delta") or {}
    assert delta.get("events") == -10
    assert delta.get("entities") == 15
    assert delta.get("links") == 10
    assert delta.get("relations") == -2

    by_type = {d.get("type"): d.get("delta") for d in (diff.get("entity_types_delta") or [])}
    assert by_type.get("Skill") == 5
    assert by_type.get("Tool") == -5
    assert by_type.get("Person") == 3


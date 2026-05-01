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


def test_diff_kg_snapshots_reports_exact_node_and_edge_drift() -> None:
    from app.rag.kg.snapshot import diff_kg_snapshots

    a = {
        "schema": "mimirq.kg_snapshot.v2",
        "pipeline_hash": "v1",
        "nodes": [
            {"id": "entity:1", "kind": "entity", "type": "Skill", "name": "Parser", "props_hash": "node-a"},
            {"id": "entity:2", "kind": "entity", "type": "Tool", "name": "Legacy", "props_hash": "same"},
        ],
        "edges": [
            {"id": "relation:1", "src": "entity:1", "dst": "entity:2", "kind": "relation", "predicate": "uses", "props_hash": "edge-a"},
            {"id": "relation:2", "src": "entity:2", "dst": "entity:1", "kind": "relation", "predicate": "depends_on", "props_hash": "same"},
        ],
    }
    b = {
        "schema": "mimirq.kg_snapshot.v2",
        "pipeline_hash": "v2",
        "nodes": [
            {"id": "entity:1", "kind": "entity", "type": "Skill", "name": "Parser", "props_hash": "node-b"},
            {"id": "entity:3", "kind": "entity", "type": "Person", "name": "Owner", "props_hash": "new"},
        ],
        "edges": [
            {"id": "relation:1", "src": "entity:1", "dst": "entity:3", "kind": "relation", "predicate": "owned_by", "props_hash": "edge-b"},
            {"id": "relation:3", "src": "entity:3", "dst": "entity:1", "kind": "relation", "predicate": "reviews", "props_hash": "new"},
        ],
    }

    diff = diff_kg_snapshots(a, b)

    assert diff.get("schema") == "mimirq.kg_snapshot_diff.v2"
    assert diff.get("node_diff") == {"added_count": 1, "removed_count": 1, "changed_count": 1, "sample_limit": 200}
    assert diff.get("edge_diff") == {"added_count": 1, "removed_count": 1, "changed_count": 1, "sample_limit": 200}
    assert [n.get("id") for n in diff.get("nodes_added") or []] == ["entity:3"]
    assert [n.get("id") for n in diff.get("nodes_removed") or []] == ["entity:2"]
    assert [n.get("id") for n in diff.get("nodes_changed") or []] == ["entity:1"]
    assert [e.get("id") for e in diff.get("edges_added") or []] == ["relation:3"]
    assert [e.get("id") for e in diff.get("edges_removed") or []] == ["relation:2"]
    assert [e.get("id") for e in diff.get("edges_changed") or []] == ["relation:1"]

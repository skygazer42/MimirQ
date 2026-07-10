
from uuid import UUID


def test_build_kg_shortest_path_provenance_prefers_direct_relation_when_available() -> None:
    from app.rag.kg.provenance import build_kg_shortest_path_provenance

    ev_id = UUID(int=1)
    doc_id = UUID(int=2)
    chunk_id = UUID(int=3)

    e1 = UUID(int=10)
    e2 = UUID(int=11)

    rel_id = UUID(int=100)
    rel_doc = UUID(int=200)
    rel_chunk = UUID(int=201)
    rel_event = UUID(int=202)

    out = build_kg_shortest_path_provenance(
        event={"id": ev_id, "document_id": doc_id, "chunk_id": chunk_id},
        entities=[{"id": e1, "type": "Skill"}, {"id": e2, "type": "Tool"}],
        key_entity_ids={str(e1), str(e2)},
        relations=[
            {
                "id": rel_id,
                "subject_entity_id": e1,
                "object_entity_id": e2,
                "predicate": "related_to",
                "confidence": 0.6,
                "document_id": rel_doc,
                "chunk_id": rel_chunk,
                "event_id": rel_event,
                "references": {"evidence_source": "mention"},
            }
        ],
        bucket_low_max=0.4,
        bucket_mid_max=0.7,
    )

    assert isinstance(out, dict)
    assert out.get("schema") == "mimirq.kg_path_provenance.v1"
    assert out.get("kind") == "entity_relation"
    assert out.get("hops") == 1

    nodes = out.get("nodes") or []
    edges = out.get("edges") or []
    assert isinstance(nodes, list) and len(nodes) == 2
    assert isinstance(edges, list) and len(edges) == 1

    assert nodes[0].get("kind") == "entity"
    assert nodes[1].get("kind") == "entity"
    assert {nodes[0].get("entity_id"), nodes[1].get("entity_id")} == {str(e1), str(e2)}

    e0 = edges[0] or {}
    assert e0.get("kind") == "relation"
    assert e0.get("relation_id") == str(rel_id)
    assert e0.get("predicate") == "related_to"
    assert e0.get("confidence_bucket") == "mid"
    assert e0.get("evidence_source") == "mention"
    assert e0.get("document_id") == str(rel_doc)
    assert e0.get("chunk_id") == str(rel_chunk)
    assert e0.get("event_id") == str(rel_event)


def test_build_kg_shortest_path_provenance_falls_back_to_entity_event_entity() -> None:
    from app.rag.kg.provenance import build_kg_shortest_path_provenance

    ev_id = UUID(int=1)
    doc_id = UUID(int=2)
    chunk_id = UUID(int=3)

    e1 = UUID(int=10)
    e2 = UUID(int=11)

    out = build_kg_shortest_path_provenance(
        event={"id": ev_id, "document_id": doc_id, "chunk_id": chunk_id},
        entities=[{"id": e1, "type": "Skill"}, {"id": e2, "type": "Tool"}],
        key_entity_ids={str(e1), str(e2)},
        relations=[],
        bucket_low_max=0.4,
        bucket_mid_max=0.7,
    )

    assert isinstance(out, dict)
    assert out.get("schema") == "mimirq.kg_path_provenance.v1"
    assert out.get("kind") == "entity_event_entity"
    assert out.get("hops") == 2

    nodes = out.get("nodes") or []
    edges = out.get("edges") or []
    assert isinstance(nodes, list) and len(nodes) == 3
    assert isinstance(edges, list) and len(edges) == 2

    assert nodes[0].get("kind") == "entity"
    assert nodes[1].get("kind") == "event"
    assert nodes[2].get("kind") == "entity"
    assert nodes[1].get("event_id") == str(ev_id)
    assert nodes[1].get("document_id") == str(doc_id)
    assert nodes[1].get("chunk_id") == str(chunk_id)

    assert (edges[0] or {}).get("kind") == "event_entity"
    assert (edges[1] or {}).get("kind") == "event_entity"




def test_build_kg_path_provenance_is_bounded_and_pii_safe() -> None:
    from app.rag.kg.provenance import build_kg_path_provenance

    raw_entities = [
        {"entity_id": "e2", "type": "Tool", "name": "Secret Tool Name"},
        {"id": "e1", "type": "Skill", "description": "sensitive"},
        {"entity_id": "e1", "type": "Skill"},
        {"entity_id": "e3", "type": "Person", "name": "Alice"},
    ]

    out = build_kg_path_provenance(
        entities=raw_entities,
        key_entity_ids={"e1", "e2"},
        max_entities=10,
    )

    assert out == [
        {"entity_id": "e1", "type": "Skill"},
        {"entity_id": "e2", "type": "Tool"},
    ]


def test_build_kg_path_provenance_caps_entities() -> None:
    from app.rag.kg.provenance import build_kg_path_provenance

    raw_entities = [{"entity_id": f"e{i}", "type": "T"} for i in range(10)]
    out = build_kg_path_provenance(entities=raw_entities, key_entity_ids=None, max_entities=3)
    assert len(out) == 3


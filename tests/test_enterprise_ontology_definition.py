import json

import pytest
from pydantic import ValidationError

from app.rag.kg.enterprise_ontology.definition import load_ontology_definition, validate_ontology_relation

MAINTENANCE_YAML = """
schema_version: 1
ontology: maintenance
object_types:
  equipment:
    key: [equipment_id]
    properties:
      equipment_id: string
      name: string
  work_order:
    key: [order_id]
    properties:
      order_id: string
      equipment_id: string
      due_at: datetime
      status: {type: string, enum: [OPEN, CLOSED]}
relations:
  order_for_equipment:
    from: work_order
    to: equipment
    cardinality: many_to_one
bindings:
  - object_type: equipment
    role: primary
    asset_id: ops.equipment
    identity_columns: [id]
    columns: {equipment_id: id, name: name}
  - object_type: work_order
    role: primary
    asset_id: ops.work_orders
    identity_columns: [id]
    columns: {order_id: id, equipment_id: asset_id, due_at: deadline, status: state}
relation_bindings:
  order_for_equipment:
    source_columns: [asset_id]
    target_columns: [id]
"""


def test_enterprise_ontology_yaml_and_json_share_the_validated_definition():
    definition = load_ontology_definition(MAINTENANCE_YAML, format="yaml")
    data = definition.model_dump(mode="json", by_alias=True)
    assert load_ontology_definition(json.dumps(data), format="json") == definition
    assert validate_ontology_relation(definition, "order_for_equipment", "work_order", "equipment") is None
    assert validate_ontology_relation(definition, "order_for_equipment", "equipment", "work_order") == (
        "relation_endpoint_type_mismatch"
    )
    assert validate_ontology_relation(definition, "unknown", "work_order", "equipment") == "unknown_relation"


@pytest.mark.parametrize(
    ("before", "after", "message"),
    [
        ("ontology: maintenance", "ontology: maintenance\nontology: other", "Duplicate key"),
        ("equipment_id: string", "equipment_id: invalid", "string"),
        ("    to: equipment", "    to: missing", "Unknown object type"),
        ("target_columns: [id]", "target_columns: [missing]", "Unmapped relation column"),
        ("identity_columns: [id]", "identity_columns: [name]", "Identity columns"),
    ],
)
def test_enterprise_ontology_rejects_invalid_definitions(before, after, message):
    with pytest.raises((ValidationError, ValueError), match=message):
        load_ontology_definition(MAINTENANCE_YAML.replace(before, after, 1), format="yaml")


def test_ontology_rejects_conflicting_rule_conditions():
    rules = """
rules:
  overdue:
    object_type: work_order
    conditions:
      - {property: status, operator: eq, value: OPEN}
      - {property: status, operator: eq, value: CLOSED}
"""
    definition = load_ontology_definition(MAINTENANCE_YAML + rules, format="yaml")
    with pytest.raises(ValueError, match="Contradictory conditions for status in rule overdue"):
        definition.validate_rules_for_publication()

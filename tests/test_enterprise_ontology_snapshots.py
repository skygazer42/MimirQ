import sqlite3

from app.rag.kg.enterprise_ontology.definition import load_ontology_definition
from app.rag.kg.enterprise_ontology.snapshots import check_sample, select_columns
from tests.test_enterprise_ontology_definition import MAINTENANCE_YAML


def test_binding_preview_preserves_business_keys_and_catches_bad_sample_rows():
    definition = load_ontology_definition(MAINTENANCE_YAML, format="yaml")
    binding = definition.bindings[1]
    object_type = definition.object_types[binding.object_type]
    with sqlite3.connect(":memory:") as db:
        db.execute("CREATE TABLE sheet_0 (id TEXT, asset_id TEXT, deadline TEXT, state TEXT)")
        db.executemany(
            "INSERT INTO sheet_0 VALUES (?, ?, ?, ?)",
            [
                ("WO-1", "E-102", "2026-11-10T12:00:00-08:00", "OPEN"),
                ("WO-2", "E-103", "2026-11-11T12:00:00-08:00", "invalid"),
            ],
        )
        rows = db.execute(select_columns("sheet_0", binding.columns)).fetchall()
    sample, issues = check_sample(binding, object_type, rows)
    assert sample[0]["order_id"] == "WO-1"
    assert sample[0]["equipment_id"] == "E-102"
    assert any(issue.code == "invalid_value" and issue.field == "status" for issue in issues)

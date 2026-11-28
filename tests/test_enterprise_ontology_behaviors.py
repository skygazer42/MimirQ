from datetime import datetime

from app.rag.kg.enterprise_ontology.behaviors import evaluate_rule
from app.rag.kg.enterprise_ontology.definition import RuleDefinition


def test_overdue_rule_requires_a_known_date_and_open_status():
    rule = RuleDefinition.model_validate({
        "object_type": "work_order",
        "conditions": [{"property": "due_at", "operator": "lt", "operand": "observed_at"},
                       {"property": "status", "operator": "eq", "value": "OPEN"}],
    })
    now = datetime.fromisoformat("2026-11-23T12:00:00-08:00")
    assert evaluate_rule(rule, {"due_at": datetime.fromisoformat("2026-11-09T00:00:00-08:00"), "status": "OPEN"}, now) == "true"
    assert evaluate_rule(rule, {"status": "OPEN"}, now) == "unknown"
    assert evaluate_rule(rule, {"status": "CLOSED"}, now) == "false"

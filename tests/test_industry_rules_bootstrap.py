from __future__ import annotations

from app.rag.industry_rules.appliers.query_rewrite import expand_query_terms
from app.rag.industry_rules.loaders.yaml_loader import load_ruleset


def test_load_industrial_control_ruleset_and_expand_query_terms() -> None:
    ruleset = load_ruleset("industrial_control")
    expanded = expand_query_terms("485 没数据", ruleset.glossary)

    assert ruleset.name == "industrial_control"
    assert "485" in ruleset.glossary
    assert "RS-485" in expanded

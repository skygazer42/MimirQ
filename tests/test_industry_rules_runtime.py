from __future__ import annotations


def test_industry_rules_query_expansion_is_off_by_default() -> None:
    from app.rag.industry_rules.runtime import apply_industry_rules_query_expansion

    query, meta = apply_industry_rules_query_expansion(
        "485 通讯失败",
        enabled=False,
        ruleset_names=["industrial_control"],
    )

    assert query == "485 通讯失败"
    assert meta["enabled"] is False
    assert meta["used"] is False
    assert meta["rulesets_requested"] == ["industrial_control"]
    assert "485 通讯失败" not in str(meta)


def test_industry_rules_query_expansion_uses_ruleset_glossary_without_leaking_query() -> None:
    from app.rag.industry_rules.runtime import apply_industry_rules_query_expansion

    query, meta = apply_industry_rules_query_expansion(
        "485 通讯失败",
        enabled=True,
        ruleset_names=["industrial_control"],
        max_aliases=2,
    )

    assert "485 通讯失败" in query
    assert "RS-485" in query
    assert meta["schema"] == "mimirq.industry_rules_runtime.v1"
    assert meta["used"] is True
    assert meta["rulesets_used"] == ["industrial_control"]
    assert meta["alias_count"] == 2
    assert "query_hash" in meta
    assert "485 通讯失败" not in str(meta)


def test_industry_rules_ruleset_names_are_deduplicated_and_capped() -> None:
    from app.rag.industry_rules.runtime import normalize_ruleset_names

    assert normalize_ruleset_names("industrial_control, industrial_control; demo", max_items=2) == [
        "industrial_control",
        "demo",
    ]

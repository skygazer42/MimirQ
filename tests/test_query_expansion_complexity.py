from app.query.expand import (
    coerce_expansion_rules,
    generate_dictionary_expansions,
    load_base_dictionary_rules,
)
from app.rag.query_expansion import coerce_query_aliases, generate_alias_queries


def test_query_rule_coercers_preserve_normalization_and_stable_deduplication() -> None:
    raw = {
        " SSO ": ["SSO", "Single Sign-On", "single sign-on", "单点登录", "单点登录", "", None],
        "LLM": "large language model",
        "": ["ignored"],
        "ignored": {"not": "a list"},
    }
    expected = {
        "SSO": ["Single Sign-On", "单点登录"],
        "LLM": ["large language model"],
    }

    assert coerce_query_aliases(raw) == expected
    assert coerce_expansion_rules(raw) == expected
    assert coerce_query_aliases(["not", "a", "mapping"]) == {}
    assert coerce_expansion_rules(None) == {}


def test_generate_alias_queries_preserves_pair_order_limits_and_trace_metadata() -> None:
    variants, metadata = generate_alias_queries(
        query="Use SSO for 单点登录",
        aliases={
            "SSO": ["single sign-on", "sso"],
            "单点登录": ["统一登录"],
        },
        max_queries=3,
        max_rules=20,
        max_query_chars=400,
    )

    assert variants == [
        "Use single sign-on for 单点登录",
        "Use sso for 单点登录",
        "Use SSO for 统一登录",
    ]
    assert metadata == {
        "enabled": True,
        "used": True,
        "base_query_chars": len("Use SSO for 单点登录"),
        "max_queries": 3,
        "rules_total": 3,
        "rules_considered": 5,
        "generated": 3,
        "applied": [
            {"src": "SSO", "tgt": "single sign-on"},
            {"src": "SSO", "tgt": "sso"},
            {"src": "单点登录", "tgt": "统一登录"},
        ],
        "queries": variants,
    }


def test_generate_alias_queries_preserves_disabled_and_truncation_contracts() -> None:
    assert generate_alias_queries(query=" ", aliases={"a": ["b"]}) == (
        [],
        {"enabled": False, "used": False, "reason": "empty_query"},
    )
    assert generate_alias_queries(query="a", aliases={"a": ["b"]}, max_queries=0) == (
        [],
        {"enabled": False, "used": False, "reason": "max_queries_le_0"},
    )
    variants, _ = generate_alias_queries(
        query="alpha suffix",
        aliases={"alpha": ["replacement"]},
        max_query_chars=5,
    )
    assert variants == ["repla..."]


def test_generate_dictionary_expansions_preserves_word_boundaries_and_budgets() -> None:
    expansions, metadata = generate_dictionary_expansions(
        query="SSO and SSO_value and 单点登录",
        rules={
            "SSO": ["single sign-on", "federated login", "third"],
            "单点登录": ["统一登录"],
        },
        max_expansions_total=3,
        max_expansions_per_rule=2,
    )

    assert expansions == [
        {
            "expanded_text": "single sign-on and SSO_value and 单点登录",
            "source_rule_id": "dict:SSO",
            "weight": 1.0,
            "src": "SSO",
            "tgt": "single sign-on",
        },
        {
            "expanded_text": "federated login and SSO_value and 单点登录",
            "source_rule_id": "dict:SSO",
            "weight": 1.0,
            "src": "SSO",
            "tgt": "federated login",
        },
        {
            "expanded_text": "SSO and SSO_value and 统一登录",
            "source_rule_id": "dict:单点登录",
            "weight": 1.0,
            "src": "单点登录",
            "tgt": "统一登录",
        },
    ]
    assert metadata["generated"] == 3
    assert metadata["max_expansions_total"] == 3
    assert metadata["max_expansions_per_rule"] == 2


def test_generate_dictionary_expansions_preserves_disabled_contracts() -> None:
    assert generate_dictionary_expansions(query=" ", rules={"a": ["b"]}) == (
        [],
        {"enabled": False, "used": False, "reason": "empty_query"},
    )
    assert generate_dictionary_expansions(
        query="a",
        rules={"a": ["b"]},
        max_expansions_per_rule=0,
    ) == ([], {"enabled": False, "used": False, "reason": "disabled"})
    assert generate_dictionary_expansions(query="a", rules={}) == (
        [],
        {"enabled": False, "used": False, "reason": "no_rules"},
    )


def test_load_base_dictionary_rules_preserves_bundled_yaml_subset() -> None:
    assert load_base_dictionary_rules() == {
        "SLO": [
            "service level objective",
            "service-level objective",
            "service level objectives",
        ],
        "SSO": ["single sign-on", "single sign on"],
        "LLM": ["large language model"],
    }

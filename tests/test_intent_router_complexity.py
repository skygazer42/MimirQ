import pytest

import app.rag.retrieval.orchestration.intent_router as intent_router
from app.rag.retrieval.orchestration.intent_router import (
    ADAPTIVE_ROUTER_POLICY_SCHEMA_V1,
    INTENT_ROUTER_POLICY_SCHEMA_V1,
    normalize_adaptive_router_policy,
    normalize_intent_router_policy,
    route_adaptive_retrieval_overrides,
    route_retrieval_preset,
)


def test_normalize_intent_router_policy_filters_rules_and_clamps_overrides() -> None:
    policy = normalize_intent_router_policy(
        {
            "schema": INTENT_ROUTER_POLICY_SCHEMA_V1,
            "rules": [
                {
                    "rule_id": " priority ",
                    "match_any": [" Priority ", "priority", ""],
                    "overrides": {
                        "retrieval_mode": "VECTOR",
                        "retrieval_profile": "recall20",
                        "top_k": "999",
                        "reranker_top_n": 0,
                        "vector_weight": -1,
                        "score_threshold": 2,
                        "enable_reranker": "yes",
                        "reranker_provider": "X" * 60,
                        "unknown": "ignored",
                    },
                },
                {"rule_id": "no-match", "match_any": [], "overrides": {"top_k": 5}},
                {"rule_id": "no-overrides", "match_any": ["x"], "overrides": {}},
            ],
        }
    )

    assert policy == {
        "schema": INTENT_ROUTER_POLICY_SCHEMA_V1,
        "rules": [
            {
                "rule_id": "priority",
                "match_any": ["Priority"],
                "match_all": [],
                "overrides": {
                    "retrieval_mode": "vector",
                    "retrieval_profile": "recall20",
                    "top_k": 200,
                    "reranker_top_n": 1,
                    "vector_weight": 0.0,
                    "score_threshold": 1.0,
                    "enable_reranker": True,
                    "reranker_provider": "x" * 40,
                },
            }
        ],
    }
    assert normalize_intent_router_policy({"schema": "wrong", "rules": []}) is None


def test_route_retrieval_preset_preserves_log_defaults_and_profile_contract() -> None:
    overrides, meta = route_retrieval_preset(
        query="ERROR GET /users failed",
        retrieval_mode="hybrid",
        retrieval_profile=None,
        top_k=5,
        score_threshold=0.4,
        enable_reranker=True,
        enable_weight_rerank=True,
        enable_multi_query=None,
        enable_query_alias_expansion=True,
    )

    assert overrides == {
        "retrieval_mode": "keyword",
        "retrieval_profile": "recall20",
        "enable_reranker": False,
        "enable_weight_rerank": False,
        "enable_multi_query": False,
        "enable_query_alias_expansion": False,
        "top_k": 20,
        "score_threshold": 0.0,
    }
    assert meta["intent"] == "log"
    assert meta["used"] is True
    assert meta["policy_used"] is False
    assert meta["learned_router"]["enabled"] is False
    assert meta["overrides"] == sorted(overrides)


def test_route_retrieval_preset_applies_policy_before_profile_contract() -> None:
    policy = {
        "schema": INTENT_ROUTER_POLICY_SCHEMA_V1,
        "rules": [
            {
                "rule_id": "priority",
                "match_any": ["priority"],
                "overrides": {"retrieval_mode": "vector", "top_k": 7},
            }
        ],
    }

    overrides, meta = route_retrieval_preset(
        query="what is priority",
        retrieval_mode="hybrid",
        retrieval_profile=None,
        top_k=3,
        score_threshold=0.5,
        enable_reranker=False,
        enable_weight_rerank=False,
        enable_multi_query=False,
        enable_query_alias_expansion=False,
        intent_router_policy=policy,
    )

    assert overrides == {
        "retrieval_profile": "recall50",
        "retrieval_mode": "vector",
        "top_k": 50,
        "score_threshold": 0.0,
    }
    assert meta["policy_rule_ids"] == ["priority"]
    assert meta["policy_used"] is True


def test_route_retrieval_preset_learned_hint_only_fills_missing_overrides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(intent_router, "normalize_intent_router_model", lambda model: {"ready": True})
    monkeypatch.setattr(
        intent_router,
        "predict_learned_router_hint",
        lambda **kwargs: {
            "confidence": 0.8,
            "rule_id": "learned-rule",
            "overrides": {"top_k": 10, "enable_reranker": True},
        },
    )

    overrides, meta = route_retrieval_preset(
        query="ERROR failed",
        retrieval_mode="hybrid",
        retrieval_profile=None,
        top_k=3,
        score_threshold=0.5,
        enable_reranker=True,
        enable_weight_rerank=False,
        enable_multi_query=False,
        enable_query_alias_expansion=False,
        learned_router_model={"raw": True},
        learned_router_confidence_min=0.7,
    )

    assert overrides["enable_reranker"] is False
    assert overrides["top_k"] == 20
    assert meta["learned_router"] == {
        "enabled": True,
        "used": True,
        "rule_id": "learned-rule",
        "confidence": 0.8,
        "confidence_gate": 0.7,
        "applied_overrides": ["top_k"],
        "skipped_reason": None,
    }


def test_normalize_and_route_adaptive_policy_preserves_conditions_and_signals() -> None:
    raw_policy = {
        "schema": ADAPTIVE_ROUTER_POLICY_SCHEMA_V1,
        "rules": [
            {
                "rule_id": " digits ",
                "when": {
                    "intent_in": ["general", "GENERAL", "invalid"],
                    "retrieval_mode_in": ["hybrid"],
                    "query_len_bucket_in": ["short"],
                    "contains_any": [" order ", "order"],
                    "has_quotes": "false",
                    "has_digits": "true",
                },
                "overrides": {"top_k": 12, "enable_multi_query": "off"},
            },
            {"rule_id": "empty", "when": {}, "overrides": {"top_k": 1}},
        ],
    }

    normalized = normalize_adaptive_router_policy(raw_policy)
    assert normalized == {
        "schema": ADAPTIVE_ROUTER_POLICY_SCHEMA_V1,
        "rules": [
            {
                "rule_id": "digits",
                "when": {
                    "intent_in": ["general"],
                    "retrieval_mode_in": ["hybrid"],
                    "query_len_bucket_in": ["short"],
                    "contains_any": ["order"],
                    "has_quotes": False,
                    "has_digits": True,
                },
                "overrides": {"top_k": 12, "enable_multi_query": False},
            }
        ],
    }

    overrides, meta = route_adaptive_retrieval_overrides(
        query="order 123",
        retrieval_mode="hybrid",
        intent_meta={"intent": "general"},
        adaptive_router_policy=raw_policy,
    )
    assert overrides == {"top_k": 12, "enable_multi_query": False}
    assert meta == {
        "enabled": True,
        "used": True,
        "rule_count": 1,
        "matched_rule_ids": ["digits"],
        "signals": {
            "intent": "general",
            "retrieval_mode": "hybrid",
            "query_len_bucket": "short",
            "has_quotes": False,
            "has_digits": True,
        },
        "overrides": ["enable_multi_query", "top_k"],
    }

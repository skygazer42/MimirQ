import pytest

from app.rag.policy import intent_router as policy_router
from app.rag.retrieval.orchestration import intent_router as orchestration_router


def test_policy_router_normalization_matches_orchestration_contract() -> None:
    intent_policy = {
        "schema": policy_router._INTENT_ROUTER_POLICY_SCHEMA_V1,
        "rules": [
            {
                "rule_id": "priority",
                "match_any": [" Priority ", "priority"],
                "overrides": {
                    "retrieval_mode": "VECTOR",
                    "retrieval_profile": "recall20",
                    "top_k": 999,
                    "score_threshold": -1,
                    "enable_reranker": "yes",
                    "reranker_provider": "Provider",
                    "unknown": "ignored",
                },
            }
        ],
    }
    adaptive_policy = {
        "schema": policy_router._ADAPTIVE_ROUTER_POLICY_SCHEMA_V1,
        "rules": [
            {
                "rule_id": "quoted",
                "when": {
                    "intent_in": ["general", "invalid"],
                    "retrieval_mode_in": ["hybrid"],
                    "contains_any": ["order"],
                    "has_quotes": True,
                },
                "overrides": {"top_k": 12},
            }
        ],
    }

    assert policy_router.normalize_intent_router_policy(
        intent_policy
    ) == orchestration_router.normalize_intent_router_policy(intent_policy)
    assert policy_router.normalize_adaptive_router_policy(
        adaptive_policy
    ) == orchestration_router.normalize_adaptive_router_policy(adaptive_policy)


@pytest.mark.parametrize(
    ("query", "profile"),
    [
        ("ERROR GET /users failed", None),
        ("what is priority", None),
        ("ordinary long-form request", "coverage80"),
    ],
)
def test_policy_router_preset_matches_orchestration_contract(query: str, profile: str | None) -> None:
    kwargs = {
        "query": query,
        "retrieval_mode": "hybrid",
        "retrieval_profile": profile,
        "top_k": 5,
        "score_threshold": 0.4,
        "enable_reranker": True,
        "enable_weight_rerank": True,
        "enable_multi_query": None,
        "enable_query_alias_expansion": True,
        "intent_router_policy": {
            "schema": policy_router._INTENT_ROUTER_POLICY_SCHEMA_V1,
            "rules": [
                {
                    "rule_id": "priority",
                    "match_any": ["priority"],
                    "overrides": {"retrieval_mode": "vector", "top_k": 7},
                }
            ],
        },
    }

    assert policy_router.route_retrieval_preset(**kwargs) == orchestration_router.route_retrieval_preset(**kwargs)


def test_policy_router_adaptive_result_matches_orchestration_contract() -> None:
    adaptive_policy = {
        "schema": policy_router._ADAPTIVE_ROUTER_POLICY_SCHEMA_V1,
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
    kwargs = {
        "query": "order 123",
        "retrieval_mode": "hybrid",
        "intent_meta": {"intent": "general"},
        "adaptive_router_policy": adaptive_policy,
    }

    assert policy_router.route_adaptive_retrieval_overrides(
        **kwargs
    ) == orchestration_router.route_adaptive_retrieval_overrides(**kwargs)

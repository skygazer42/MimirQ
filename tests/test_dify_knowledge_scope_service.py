import json
from uuid import uuid4

import pytest
from fastapi import HTTPException


def test_resolve_scope_applies_strict_inherited_replace_route(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.dify_integration import knowledge_scope

    base_dataset = uuid4()
    route_dataset = uuid4()
    monkeypatch.setattr(
        knowledge_scope.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_MAP_JSON",
        (
            "{"
            '"route-source": {'
            f'"dataset_ids": ["{route_dataset}"],'
            '"query_routes": [{"terms": ["region alpha"], '
            f'"dataset_ids": ["{route_dataset}"], "mode": "replace"}}]'
            "},"
            '"target": {'
            f'"dataset_ids": ["{base_dataset}"],'
            '"strict_query_routes": true,'
            '"inherit_query_routes_from": ["route-source"]'
            "}"
            "}"
        ),
        raising=False,
    )

    scope = knowledge_scope.resolve_scope("target", query="region alpha service")

    assert scope.strict_scope is True
    assert list(scope.dataset_ids) == [route_dataset]
    assert list(scope.primary_dataset_ids) == [route_dataset]


def test_resolve_scope_rejects_direct_dataset_uuid_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.dify_integration import knowledge_scope

    dataset_id = uuid4()
    monkeypatch.setattr(knowledge_scope.settings, "DIFY_EXTERNAL_KNOWLEDGE_MAP_JSON", "{}", raising=False)
    monkeypatch.setattr(knowledge_scope.settings, "DIFY_EXTERNAL_KNOWLEDGE_RESOLUTION_MODE", "allow_dataset_uuid")
    monkeypatch.setattr(knowledge_scope, "is_production_env", lambda: True, raising=True)

    with pytest.raises(HTTPException) as exc_info:
        knowledge_scope.resolve_scope(str(dataset_id), query="query")

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Dify knowledge mapping not found"


def test_policy_fallback_multiplier_uses_default_for_invalid_configured_max() -> None:
    from app.services.dify_integration.policy_helpers import apply_policy_fallback_candidate_multiplier

    assert apply_policy_fallback_candidate_multiplier(7, multiplier=9, configured_max="bad") == 50
    assert apply_policy_fallback_candidate_multiplier(60, multiplier=1, configured_max="bad") == 60


def test_sibling_scope_requires_opt_in_and_a_specific_service_query(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.dify_integration import knowledge_scope, policy_helpers

    base_dataset = uuid4()
    sibling_dataset = uuid4()
    plugin_ref = "plugin:scope-test@1.0:chunk"
    policy = {
        "schema": "mimirq.retrieval_policy.v1",
        "service_anchor_entity_terms": ["核准"],
        "service_anchor_noise_terms": ["这个事项", "行使层级", "办理材料"],
        "service_anchor_cutoff_terms": ["这个事项"],
    }
    monkeypatch.setattr(policy_helpers, "retrieval_policy_for_plugin_ref", lambda _ref: policy)
    monkeypatch.setattr(
        knowledge_scope.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_MAP_JSON",
        json.dumps(
            {
                "city": {
                    "dataset_ids": [str(base_dataset)],
                    "plugin_refs": [plugin_ref],
                    "query_routes": [{"terms": ["district"], "dataset_ids": [str(sibling_dataset)], "mode": "replace"}],
                },
                "district": {"dataset_ids": [str(sibling_dataset)], "plugin_refs": [plugin_ref]},
            }
        ),
    )
    monkeypatch.setattr(
        knowledge_scope.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_EXTENDED_SCOPE_MAX_DATASETS",
        80,
    )
    monkeypatch.setattr(
        knowledge_scope.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_EXTEND_SIBLING_POLICY_SCOPE_ENABLED",
        False,
    )
    args = {
        "knowledge_id": "city",
        "base_dataset_ids": [base_dataset],
        "policy_plugin_refs": (plugin_ref,),
    }
    query = "城市建筑垃圾处置核准这个事项，行使层级、办理材料。"
    assert knowledge_scope.extend_sibling_policy_scope(query=query, **args) == [base_dataset]

    monkeypatch.setattr(
        knowledge_scope.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_EXTEND_SIBLING_POLICY_SCOPE_ENABLED",
        True,
    )
    assert knowledge_scope.extend_sibling_policy_scope(query=query, **args) == [base_dataset, sibling_dataset]
    assert knowledge_scope.extend_sibling_policy_scope(query="核准", **args) == [base_dataset]

from __future__ import annotations

import uuid

import pytest

from app.rag.retrieval import planner
from app.rag.retrieval.planner import (
    DatasetRouteHint,
    compact_high_confidence_items,
    plan_dataset_scope,
    resolve_internal_candidate_top_k,
    retrieval_policy_boost_score,
    retrieval_policy_fallback_multiplier,
    retrieval_policy_query_terms,
    retrieval_policy_rerank_feature_score,
    retrieval_policy_response_compaction,
)


def test_resolve_internal_candidate_top_k_respects_min_multiplier_and_max() -> None:
    assert resolve_internal_candidate_top_k(5, minimum=20, multiplier=4, maximum=50) == 20
    assert resolve_internal_candidate_top_k(10, minimum=20, multiplier=4, maximum=50) == 40
    assert resolve_internal_candidate_top_k(20, minimum=20, multiplier=4, maximum=50) == 50


def test_resolve_internal_candidate_top_k_never_goes_below_requested() -> None:
    assert resolve_internal_candidate_top_k(80, minimum=20, multiplier=4, maximum=50) == 80


def test_plan_dataset_scope_treats_routes_as_recall_hints_by_default() -> None:
    base_dataset = uuid.uuid4()
    one_thing_dataset = uuid.uuid4()
    department_qa_dataset = uuid.uuid4()

    plan = plan_dataset_scope(
        base_dataset_ids=[base_dataset],
        route_hints=[
            DatasetRouteHint(terms=("一件事",), dataset_ids=(one_thing_dataset,), mode="replace"),
            DatasetRouteHint(terms=("不动产",), dataset_ids=(department_qa_dataset,), mode="replace"),
        ],
        query="普通查询",
    )

    assert plan.dataset_ids == (base_dataset, one_thing_dataset, department_qa_dataset)
    assert plan.primary_dataset_ids == (base_dataset, one_thing_dataset, department_qa_dataset)
    assert plan.expansion_dataset_ids == ()
    assert plan.strict_scope is False
    assert plan.matched_route_count == 0
    assert plan.included_hint_dataset_count == 2


def test_plan_dataset_scope_does_not_gate_unmatched_hint_datasets_behind_base_scope() -> None:
    base_dataset = uuid.uuid4()
    faq_dataset = uuid.uuid4()

    plan = plan_dataset_scope(
        base_dataset_ids=[base_dataset],
        route_hints=[DatasetRouteHint(terms=("补贴",), dataset_ids=(faq_dataset,), mode="replace")],
        query="资金使用有哪些要求",
    )

    assert plan.dataset_ids == (base_dataset, faq_dataset)
    assert plan.primary_dataset_ids == (base_dataset, faq_dataset)
    assert plan.expansion_dataset_ids == ()
    assert plan.matched_route_count == 0


def test_plan_dataset_scope_prioritizes_matched_route_hints() -> None:
    base_dataset = uuid.uuid4()
    one_thing_dataset = uuid.uuid4()
    department_qa_dataset = uuid.uuid4()

    plan = plan_dataset_scope(
        base_dataset_ids=[base_dataset],
        route_hints=[
            DatasetRouteHint(terms=("一件事",), dataset_ids=(one_thing_dataset,), mode="replace"),
            DatasetRouteHint(terms=("不动产",), dataset_ids=(department_qa_dataset,), mode="replace"),
        ],
        query="不动产登记交易中心地址",
    )

    assert plan.dataset_ids == (department_qa_dataset, base_dataset, one_thing_dataset)
    assert plan.primary_dataset_ids == (department_qa_dataset, base_dataset, one_thing_dataset)
    assert plan.expansion_dataset_ids == ()
    assert plan.matched_route_count == 1
    assert plan.matched_terms == ("不动产",)


def test_plan_dataset_scope_can_use_matched_replace_routes_as_primary_scope() -> None:
    base_dataset = uuid.uuid4()
    one_thing_dataset = uuid.uuid4()
    department_qa_dataset = uuid.uuid4()

    plan = plan_dataset_scope(
        base_dataset_ids=[base_dataset],
        route_hints=[
            DatasetRouteHint(terms=("一件事",), dataset_ids=(one_thing_dataset,), mode="replace"),
            DatasetRouteHint(terms=("不动产",), dataset_ids=(department_qa_dataset,), mode="replace"),
        ],
        query="不动产登记交易中心地址",
        matched_replace_routes_as_primary_scope=True,
    )

    assert plan.dataset_ids == (department_qa_dataset, base_dataset, one_thing_dataset)
    assert plan.primary_dataset_ids == (department_qa_dataset,)
    assert plan.expansion_dataset_ids == (base_dataset, one_thing_dataset)
    assert plan.matched_route_count == 1
    assert plan.matched_terms == ("不动产",)


def test_plan_dataset_scope_can_apply_strict_replace_routes() -> None:
    base_dataset = uuid.uuid4()
    route_dataset = uuid.uuid4()

    unmatched = plan_dataset_scope(
        base_dataset_ids=[base_dataset],
        route_hints=[DatasetRouteHint(terms=("区域甲",), dataset_ids=(route_dataset,), mode="replace")],
        query="普通查询",
        strict_routes=True,
    )
    matched = plan_dataset_scope(
        base_dataset_ids=[base_dataset],
        route_hints=[DatasetRouteHint(terms=("区域甲",), dataset_ids=(route_dataset,), mode="replace")],
        query="区域甲服务卡补卡在哪里办理",
        strict_routes=True,
    )

    assert unmatched.dataset_ids == (base_dataset,)
    assert unmatched.primary_dataset_ids == (base_dataset,)
    assert unmatched.expansion_dataset_ids == ()
    assert matched.dataset_ids == (route_dataset,)
    assert matched.primary_dataset_ids == (route_dataset,)
    assert matched.expansion_dataset_ids == ()
    assert matched.strict_scope is True


def test_plan_dataset_scope_dedupes_route_and_base_datasets() -> None:
    base_dataset = uuid.uuid4()
    route_dataset = uuid.uuid4()

    plan = plan_dataset_scope(
        base_dataset_ids=[base_dataset, route_dataset],
        route_hints=[
            DatasetRouteHint(terms=("服务卡",), dataset_ids=(route_dataset, base_dataset), mode="prepend"),
        ],
        query="服务卡在哪里补办",
    )

    assert plan.dataset_ids == (route_dataset, base_dataset)


def test_compact_high_confidence_items_drops_score_cliff_noise() -> None:
    items = ["exact", "near-noise", "noise"]
    scores = [0.92, 0.38, 0.34]

    assert compact_high_confidence_items(
        items,
        scores=scores,
        top_k=3,
        enabled=True,
        min_top_score=0.8,
        relative_score_floor=0.65,
        min_items=1,
    ) == ("exact",)


def test_compact_high_confidence_items_keeps_uncertain_rankings() -> None:
    items = ["maybe-a", "maybe-b", "maybe-c"]
    scores = [0.72, 0.51, 0.49]

    assert compact_high_confidence_items(
        items,
        scores=scores,
        top_k=3,
        enabled=True,
        min_top_score=0.8,
        relative_score_floor=0.65,
        min_items=1,
    ) == tuple(items)


def test_compact_high_confidence_items_honors_min_items() -> None:
    items = ["exact", "backup", "noise"]
    scores = [0.95, 0.31, 0.29]

    assert compact_high_confidence_items(
        items,
        scores=scores,
        top_k=3,
        enabled=True,
        min_top_score=0.8,
        relative_score_floor=0.65,
        min_items=2,
    ) == ("exact", "backup")


def test_retrieval_policy_extracts_query_terms_from_declared_metadata_fields() -> None:
    policy = {
        "schema": "mimirq.retrieval_policy.v1",
        "query_expansion_fields": ["record_title", "aliases", "ignored_missing"],
    }
    metadata_layers = [
        {"record_title": "账户重置", "aliases": ["密码找回", "登录恢复"]},
        {"aliases": ["备用入口", "密码找回"]},
    ]

    assert retrieval_policy_query_terms(policy, metadata_layers=metadata_layers) == (
        "账户重置",
        "密码找回",
        "登录恢复",
        "备用入口",
    )


def test_retrieval_policy_extracts_query_terms_from_declared_metadata_value_map() -> None:
    policy = {
        "schema": "mimirq.retrieval_policy.v1",
        "query_expansion_values": [
            {
                "metadata": "section_type",
                "value": "setup_steps",
                "terms": ["setup steps", "installation guide"],
            },
            {
                "metadata": "kind",
                "values": ["faq", "howto"],
                "terms": ["help center"],
            },
        ],
    }
    metadata_layers = [
        {"section_type": "setup_steps", "kind": "faq"},
        {"section_type": "setup_steps", "kind": "faq"},
    ]

    assert retrieval_policy_query_terms(policy, metadata_layers=metadata_layers) == (
        "setup steps",
        "installation guide",
        "help center",
    )


def test_retrieval_policy_boost_scores_declared_custom_fields_without_platform_business_defaults() -> None:
    policy = {
        "schema": "mimirq.retrieval_policy.v1",
        "boost_fields": [
            {"metadata": "product_line", "weight": 2.0, "match": "contains"},
            {"metadata": "aliases", "weight": 1.0, "match": "overlap"},
        ],
    }
    metadata_layers = [
        {"product_line": "Alpha Desk", "aliases": ["password reset", "account recovery"]},
    ]

    assert retrieval_policy_boost_score(
        policy,
        metadata_layers=metadata_layers,
        query="How does Alpha Desk account recovery work?",
    ) == pytest.approx(0.12)


def test_retrieval_policy_anchor_mismatch_penalizes_conflicting_declared_anchor() -> None:
    penalty = getattr(planner, "retrieval_policy_anchor_mismatch_penalty", None)
    assert callable(penalty)
    policy = {
        "schema": "mimirq.retrieval_policy.v1",
        "anchor_fields": [
            {
                "metadata": "region",
                "weight": 2.0,
                "aliases": {
                    "north": ["north", "north district"],
                    "south": ["south", "south district"],
                },
            }
        ],
    }

    assert penalty(
        policy,
        metadata_layers=[{"region": "north"}],
        query="How do I renew a permit in south district?",
    ) == pytest.approx(0.16)
    assert (
        penalty(
            policy,
            metadata_layers=[{"region": "south"}],
            query="How do I renew a permit in south district?",
        )
        == 0.0
    )
    assert (
        penalty(
            policy,
            metadata_layers=[{}],
            query="How do I renew a permit in south district?",
        )
        == 0.0
    )


def test_retrieval_policy_fallback_multiplier_uses_enabled_policy_only() -> None:
    assert (
        retrieval_policy_fallback_multiplier(
            {
                "schema": "mimirq.retrieval_policy.v1",
                "fallback": {"enabled": True, "expand_top_k_multiplier": 4},
            }
        )
        == 4
    )
    assert (
        retrieval_policy_fallback_multiplier(
            {
                "schema": "mimirq.retrieval_policy.v1",
                "fallback": {"enabled": False, "expand_top_k_multiplier": 4},
            }
        )
        == 1
    )
    assert retrieval_policy_fallback_multiplier({"schema": "other"}, default=2) == 2
    assert (
        retrieval_policy_fallback_multiplier(
            {
                "schema": "mimirq.retrieval_policy.v1",
                "fallback": {"enabled": True, "expand_top_k_multiplier": 50},
            },
            maximum=10,
        )
        == 10
    )


def test_retrieval_policy_response_compaction_reads_bounded_policy() -> None:
    assert retrieval_policy_response_compaction(
        {
            "schema": "mimirq.retrieval_policy.v1",
            "response_compaction": {
                "enabled": True,
                "min_top_score": 0.82,
                "relative_score_floor": 0.72,
                "min_records": 2,
            },
        }
    ) == {
        "enabled": True,
        "min_top_score": 0.82,
        "relative_score_floor": 0.72,
        "min_records": 2,
    }
    assert retrieval_policy_response_compaction({"schema": "other"}) == {"enabled": False}


def test_retrieval_policy_rerank_feature_score_uses_declared_metadata_fields() -> None:
    policy = {
        "schema": "mimirq.retrieval_policy.v1",
        "rerank_features": ["support_tier", "ticket_type"],
    }
    metadata_layers = [
        {"support_tier": "priority escalation", "ticket_type": "standard request"},
    ]

    assert retrieval_policy_rerank_feature_score(
        policy,
        metadata_layers=metadata_layers,
        query="priority escalation path",
    ) == pytest.approx(0.06)
    assert (
        retrieval_policy_rerank_feature_score(
            policy,
            metadata_layers=metadata_layers,
            query="billing address update",
        )
        == 0.0
    )


def test_summarize_kg_hint_diagnostics_counts_query_anchor_relation_and_noise() -> None:
    summarize = getattr(planner, "summarize_kg_hint_diagnostics", None)
    assert callable(summarize)

    records = [
        {
            "chunk_id": "chunk-a",
            "retrieval_role": "kgq",
            "kg_pagerank": 0.6,
            "kg_shared_events": 2,
            "kg_path_length": 2,
            "kg_evidence_anchored": True,
        },
        {
            "metadata": {
                "chunk_id": "chunk-b",
                "document_id": "doc-b",
                "retrieval_role": "kg",
                "kg_pagerank": 0.2,
                "kg_shared_events": 1,
                "kg_path_length": 3,
                "kg_evidence_anchored": False,
            }
        },
        {"metadata": {"chunk_id": "chunk-c", "retrieval_role": "main"}},
    ]

    diagnostics = summarize(records, expected_chunk_ids=("chunk-a",))

    assert diagnostics["schema"] == "mimirq.kg_hint_diagnostics.v1"
    assert diagnostics["record_count"] == 3
    assert diagnostics["retrieval_role_counts"] == {"kgq": 1, "kg": 1, "main": 1}
    assert diagnostics["kg_candidate_count"] == 2
    assert diagnostics["kg_query_expansion_record_count"] == 1
    assert diagnostics["kg_entity_anchor_record_count"] == 1
    assert diagnostics["kg_relation_neighbor_record_count"] == 2
    assert diagnostics["kg_boosted_record_count"] == 2
    assert diagnostics["kg_noise_evaluated"] is True
    assert diagnostics["kg_noise_record_count"] == 1
    assert diagnostics["kg_noise_rate"] == pytest.approx(0.5)


def test_summarize_kg_hint_diagnostics_does_not_invent_noise_without_expectations() -> None:
    summarize = getattr(planner, "summarize_kg_hint_diagnostics", None)
    assert callable(summarize)

    diagnostics = summarize(
        [
            {
                "metadata": {
                    "chunk_id": "chunk-a",
                    "retrieval_role": "kg",
                    "kg_pagerank": 0.4,
                    "kg_shared_events": 1,
                }
            }
        ]
    )

    assert diagnostics["kg_candidate_count"] == 1
    assert diagnostics["kg_noise_evaluated"] is False
    assert diagnostics["kg_noise_record_count"] == 0
    assert diagnostics["kg_noise_rate"] is None


def test_summarize_kg_hint_diagnostics_can_evaluate_noise_by_expected_metadata_scope() -> None:
    summarize = getattr(planner, "summarize_kg_hint_diagnostics", None)
    assert callable(summarize)

    diagnostics = summarize(
        [
            {
                "metadata": {
                    "retrieval_role": "kgq",
                    "kg_pagerank": 0.6,
                    "_evaluable_metadata": {"region": "south", "ticket_type": "permit"},
                }
            },
            {
                "metadata": {
                    "retrieval_role": "kg",
                    "kg_pagerank": 0.2,
                    "_evaluable_metadata": {"region": "north", "ticket_type": "permit"},
                }
            },
        ],
        expected_metadata={"region": "south", "ticket_type": "permit"},
        metadata_view_keys=("_evaluable_metadata",),
    )

    assert diagnostics["kg_candidate_count"] == 2
    assert diagnostics["kg_noise_evaluated"] is True
    assert diagnostics["kg_noise_record_count"] == 1
    assert diagnostics["kg_noise_rate"] == pytest.approx(0.5)

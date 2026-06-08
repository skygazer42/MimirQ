from __future__ import annotations

from typing import Any

import pytest


def _policy_resolver(plugin_ref: str) -> dict[str, Any]:
    if plugin_ref != "plugin:demo-service@1.0.0:chunk":
        return {}
    return {
        "schema": "mimirq.retrieval_policy.v1",
        "boost_fields": [{"metadata": "product_line", "weight": 2.0, "match": "contains"}],
        "query_expansion_fields": ["alias"],
        "rerank_features": ["support_tier"],
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


def _record_plugin_ref(record: dict[str, Any]) -> str:
    return str(record.get("plugin_ref") or "").strip()


def _record_metadata_layers(record: dict[str, Any]) -> list[dict[str, Any]]:
    metadata = record.get("metadata")
    return [metadata] if isinstance(metadata, dict) else []


def test_record_retrieval_policy_bonus_combines_generic_policy_signals() -> None:
    from app.rag.retrieval.plugin_policy import record_retrieval_policy_bonus

    record = {
        "plugin_ref": "plugin:demo-service@1.0.0:chunk",
        "metadata": {
            "product_line": "Alpha Desk",
            "alias": "priority escalation",
            "support_tier": "priority escalation",
            "region": "south",
        },
    }

    assert record_retrieval_policy_bonus(
        record,
        query="Alpha Desk priority escalation path in south district",
        plugin_ref_for_record=_record_plugin_ref,
        metadata_layers_for_record=_record_metadata_layers,
        policy_resolver=_policy_resolver,
    ) == pytest.approx(0.22)


def test_record_retrieval_policy_bonus_demotes_anchor_mismatch() -> None:
    from app.rag.retrieval.plugin_policy import record_retrieval_policy_bonus

    record = {
        "plugin_ref": "plugin:demo-service@1.0.0:chunk",
        "metadata": {
            "product_line": "Alpha Desk",
            "region": "north",
        },
    }

    assert record_retrieval_policy_bonus(
        record,
        query="Alpha Desk path in south district",
        plugin_ref_for_record=_record_plugin_ref,
        metadata_layers_for_record=_record_metadata_layers,
        policy_resolver=_policy_resolver,
    ) == pytest.approx(-0.08)


def test_record_retrieval_policy_bonus_supports_fuzzy_overlap_boost_fields() -> None:
    from app.rag.retrieval.plugin_policy import record_retrieval_policy_bonus

    plugin_ref = "plugin:demo-service@1.0.0:chunk"
    policy = {
        "schema": "mimirq.retrieval_policy.v1",
        "boost_fields": [{"metadata": "aliases", "weight": 2.0, "match": "fuzzy_overlap"}],
    }
    record = {
        "plugin_ref": plugin_ref,
        "metadata": {
            "aliases": ["办理汽车置换补贴"],
        },
    }

    assert record_retrieval_policy_bonus(
        record,
        query="汽车置换补贴怎么申请",
        plugin_ref_for_record=_record_plugin_ref,
        metadata_layers_for_record=_record_metadata_layers,
        policy_resolver=lambda ref: policy if ref == plugin_ref else {},
    ) == pytest.approx(0.08)


def test_record_retrieval_policy_bonus_supports_fuzzy_overlap_query_expansion_terms() -> None:
    from app.rag.retrieval.plugin_policy import record_retrieval_policy_bonus

    plugin_ref = "plugin:demo-service@1.0.0:chunk"
    policy = {
        "schema": "mimirq.retrieval_policy.v1",
        "query_expansion_fields": ["aliases"],
    }
    record = {
        "plugin_ref": plugin_ref,
        "metadata": {
            "aliases": ["办理汽车置换补贴"],
        },
    }

    assert record_retrieval_policy_bonus(
        record,
        query="汽车置换补贴怎么申请",
        plugin_ref_for_record=_record_plugin_ref,
        metadata_layers_for_record=_record_metadata_layers,
        policy_resolver=lambda ref: policy if ref == plugin_ref else {},
    ) == pytest.approx(0.08)


def test_record_retrieval_policy_bonus_supports_fuzzy_overlap_rerank_features() -> None:
    from app.rag.retrieval.plugin_policy import record_retrieval_policy_bonus

    plugin_ref = "plugin:demo-service@1.0.0:chunk"
    policy = {
        "schema": "mimirq.retrieval_policy.v1",
        "rerank_features": ["aliases"],
    }
    record = {
        "plugin_ref": plugin_ref,
        "metadata": {
            "aliases": ["办理汽车置换补贴"],
        },
    }

    assert record_retrieval_policy_bonus(
        record,
        query="汽车置换补贴怎么申请",
        plugin_ref_for_record=_record_plugin_ref,
        metadata_layers_for_record=_record_metadata_layers,
        policy_resolver=lambda ref: policy if ref == plugin_ref else {},
    ) == pytest.approx(0.06)


def test_record_retrieval_policy_bonus_demotes_value_intent_mismatch() -> None:
    from app.rag.retrieval.plugin_policy import record_retrieval_policy_bonus

    plugin_ref = "plugin:demo-service@1.0.0:chunk"
    policy = {
        "schema": "mimirq.retrieval_policy.v1",
        "query_expansion_values": [
            {"metadata": "section_type", "value": "materials", "terms": ["需要哪些材料", "办理材料"]},
            {"metadata": "section_type", "value": "channels", "terms": ["办理渠道", "在哪里办理"]},
        ],
    }
    record = {
        "plugin_ref": plugin_ref,
        "metadata": {
            "section_type": "channels",
        },
    }

    assert record_retrieval_policy_bonus(
        record,
        query="开办餐饮店一件事需要哪些材料",
        plugin_ref_for_record=_record_plugin_ref,
        metadata_layers_for_record=_record_metadata_layers,
        policy_resolver=lambda ref: policy if ref == plugin_ref else {},
    ) == pytest.approx(-0.08)


def test_records_retrieval_policy_diagnostics_summarize_shared_policy_signals() -> None:
    from app.rag.retrieval.plugin_policy import records_retrieval_policy_diagnostics

    plugin_ref = "plugin:demo-service@1.0.0:chunk"
    records = [
        {"plugin_ref": plugin_ref, "metadata": {"product_line": "Alpha Desk"}},
        {"plugin_ref": plugin_ref, "metadata": {"alias": "priority escalation"}},
        {"plugin_ref": plugin_ref, "metadata": {"support_tier": "priority escalation"}},
        {"metadata": {"product_line": "Alpha Desk"}},
    ]

    assert records_retrieval_policy_diagnostics(
        records,
        query="Alpha Desk priority escalation path",
        plugin_ref_for_record=_record_plugin_ref,
        metadata_layers_for_record=_record_metadata_layers,
        policy_resolver=_policy_resolver,
    ) == {
        "retrieval_policy_record_count": 3,
        "retrieval_policy_boosted_record_count": 3,
        "retrieval_policy_boost_field_record_count": 1,
        "retrieval_policy_query_expansion_record_count": 1,
        "retrieval_policy_rerank_feature_record_count": 1,
        "retrieval_policy_anchor_mismatch_record_count": 0,
        "retrieval_policy_plugin_refs": ["plugin:demo-service@1.0.0:chunk"],
    }

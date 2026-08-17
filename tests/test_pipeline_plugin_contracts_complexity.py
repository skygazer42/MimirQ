import pytest
from langchain_core.documents import Document

from app.rag.pipeline_plugins.contracts import (
    DISPLAY_METADATA_KEY,
    EVALUABLE_METADATA_KEY,
    INDEXED_METADATA_KEY,
    RECORD_IDENTITY_METADATA_KEY,
    PipelinePluginContractError,
    build_metadata_schema_views,
    parse_metadata_schema,
    summarize_contracts,
    validate_golden_rules_metadata_fields,
    validate_retrieval_policy_metadata_fields,
    validate_retrieval_text_schema_metadata_fields,
)


def _metadata_schema() -> dict:
    return {
        "schema": "mimirq.metadata_schema.v1",
        "fields": [
            {
                "name": "topic",
                "type": "string",
                "required": True,
                "filterable": True,
                "display": True,
                "evaluable": True,
                "max_length": 64,
                "enum": ["billing", "support"],
            },
            {
                "name": "metadata.region",
                "type": "string",
                "stages": ["chunk"],
                "filterable": True,
                "display": True,
            },
            {
                "name": "metadata.account_id",
                "type": "string",
                "stages": ["chunk"],
                "display": True,
                "evaluable": True,
            },
            {
                "name": "metadata.country",
                "type": "string",
                "stages": ["chunk"],
                "filterable": True,
            },
            {
                "name": "references.ticket_id",
                "type": "string",
                "stages": ["kg"],
            },
            {
                "name": "governance_only",
                "type": "string",
                "stages": ["governance"],
            },
            {
                "name": "metadata.chunk_kind",
                "type": "string",
                "stages": ["chunk"],
                "filterable": True,
            },
        ],
        "record_identity": ["metadata.account_id", "topic"],
    }


def test_parse_metadata_schema_trims_defaults_and_identity_fields() -> None:
    fields = parse_metadata_schema(_metadata_schema())

    assert [field.name for field in fields] == [
        "topic",
        "metadata.region",
        "metadata.account_id",
        "metadata.country",
        "references.ticket_id",
        "governance_only",
        "metadata.chunk_kind",
    ]
    assert fields[0].required is True
    assert fields[0].filterable is True
    assert fields[0].display is True
    assert fields[0].evaluable is True
    assert fields[0].max_length == 64
    assert fields[0].enum == ("billing", "support")
    assert fields[0].stages == ()
    assert fields[4].stages == ("kg",)


def test_summarize_contracts_preserves_retrieval_policy_summary_behavior() -> None:
    summary = summarize_contracts(
        metadata_schema=_metadata_schema(),
        retrieval_text_schema={"schema": "mimirq.retrieval_text_schema.v1", "stages": {"chunk": {}, "governance": {}}},
        golden_rules={"schema": "mimirq.golden_rules.v1"},
        retrieval_policy={
            "schema": "mimirq.retrieval_policy.v1",
            "query_expansion_fields": ["topic", "topic", "metadata.region"],
            "query_expansion_values": [
                {"metadata": "topic", "value": "billing", "terms": ["invoice", "invoice"]},
                {"metadata": "topic", "values": ["support"], "terms": ["help"]},
                {"metadata": "metadata.region", "value": "emea", "terms": ["europe"]},
            ],
            "question_intent_terms": ["what", "what", "where"],
            "mixed_intent_leading_noise_terms": ["please"],
            "mixed_intent_subject_terms": ["team"],
            "service_anchor_noise_terms": ["internal"],
            "service_anchor_priority_terms": ["priority"],
            "service_anchor_entity_terms": ["service"],
            "service_anchor_leading_noise_terms": ["kindly"],
            "service_anchor_cutoff_terms": ["resolved"],
            "question_anchor_generic_subject_terms": ["system"],
            "fast_response_always_labels": ["answer"],
            "fast_response_field_rules": [{"label": "answer", "markers": ["status"]}],
            "metadata_anchor_preflight_block_terms": ["ignore"],
            "service_anchor_query_rewrites": [{"terms": ["sync"], "rewrite": "synchronize"}],
            "filter_fields": ["metadata.region"],
            "boost_fields": [
                {"metadata": "topic", "weight": 2.0},
                {"metadata": "topic", "weight": 4.0},
                {"metadata": "metadata.region", "weight": 1.5},
            ],
            "anchor_fields": [
                {"metadata": "topic", "weight": 1.0},
                {"metadata": "topic", "weight": 3.0},
                {"metadata": "metadata.region", "weight": 2.0},
            ],
            "anchor_binding": {
                "enabled": True,
                "anchor_fields": ["topic", "topic"],
            },
            "rerank_features": ["topic", "metadata.account_id"],
            "fallback": {"enabled": True},
            "response_compaction": {"enabled": True},
            "response_hints": {},
        },
    )

    assert summary["metadata"]["record_identity_fields"] == ["metadata.account_id", "topic"]
    assert summary["retrieval_text"]["stages"] == ["chunk", "governance"]
    assert summary["golden"] == {"schema": "mimirq.golden_rules.v1", "enabled": True}
    assert summary["retrieval_policy"] == {
        "schema": "mimirq.retrieval_policy.v1",
        "query_expansion_fields": ["topic", "metadata.region"],
        "query_expansion_value_fields": ["topic", "metadata.region"],
        "question_intent_terms": ["what", "where"],
        "mixed_intent_leading_noise_terms": ["please"],
        "mixed_intent_subject_terms": ["team"],
        "service_anchor_noise_terms": ["internal"],
        "service_anchor_priority_terms": ["priority"],
        "service_anchor_entity_terms": ["service"],
        "service_anchor_leading_noise_terms": ["kindly"],
        "service_anchor_cutoff_terms": ["resolved"],
        "question_anchor_generic_subject_terms": ["system"],
        "fast_response_always_labels": ["answer"],
        "fast_response_field_rules": 1,
        "metadata_anchor_preflight_block_terms": ["ignore"],
        "service_anchor_query_rewrites": 1,
        "filter_fields": ["metadata.region"],
        "boost_fields": ["topic", "metadata.region"],
        "anchor_fields": ["topic", "metadata.region"],
        "anchor_binding_fields": ["topic"],
        "anchor_binding_enabled": True,
        "rerank_features": ["topic", "metadata.account_id"],
        "fallback_enabled": True,
        "response_compaction_enabled": True,
        "response_hints_enabled": True,
    }


def test_validate_golden_rules_metadata_fields_enforces_declared_evaluable_fields() -> None:
    with pytest.raises(
        PipelinePluginContractError,
        match="golden_rules.expected_metadata references non-evaluable metadata fields: metadata.region",
    ):
        validate_golden_rules_metadata_fields(
            golden_rules={
                "schema": "mimirq.golden_rules.v1",
                "expected_metadata": ["topic", "metadata.region"],
            },
            metadata_schema=_metadata_schema(),
        )


def test_validate_retrieval_text_schema_metadata_fields_accepts_content_only_entries() -> None:
    validate_retrieval_text_schema_metadata_fields(
        retrieval_text_schema={
            "schema": "mimirq.retrieval_text_schema.v1",
            "stages": {
                "chunk": {
                    "fields": [
                        {"metadata": "topic", "label": "Topic"},
                        {"content": True, "label": "Body"},
                    ]
                },
                "governance": {
                    "fields": [
                        {"metadata": "topic"},
                    ]
                },
            },
        },
        metadata_schema=_metadata_schema(),
    )


def test_validate_retrieval_text_schema_metadata_fields_rejects_undeclared_metadata() -> None:
    with pytest.raises(
        PipelinePluginContractError,
        match="retrieval_text_schema.stages.chunk.fields references undeclared metadata fields: missing",
    ):
        validate_retrieval_text_schema_metadata_fields(
            retrieval_text_schema={
                "schema": "mimirq.retrieval_text_schema.v1",
                "stages": {"chunk": {"fields": [{"metadata": "missing"}]}},
            },
            metadata_schema=_metadata_schema(),
        )


def test_validate_retrieval_policy_metadata_fields_accepts_nested_sections() -> None:
    validate_retrieval_policy_metadata_fields(
        retrieval_policy={
            "schema": "mimirq.retrieval_policy.v1",
            "query_expansion_fields": ["topic", "metadata.region"],
            "query_expansion_values": [
                {"metadata": "topic", "value": "billing", "terms": ["invoice"]},
                {"metadata": "metadata.region", "values": ["emea"], "terms": ["europe"]},
            ],
            "filter_fields": ["topic", "metadata.region"],
            "rerank_features": ["topic"],
            "question_intent_terms": ["what"],
            "mixed_intent_leading_noise_terms": ["please"],
            "mixed_intent_subject_terms": ["team"],
            "service_anchor_noise_terms": ["internal"],
            "service_anchor_priority_terms": ["priority"],
            "service_anchor_entity_terms": ["service"],
            "service_anchor_leading_noise_terms": ["kindly"],
            "service_anchor_cutoff_terms": ["resolved"],
            "question_anchor_generic_subject_terms": ["system"],
            "fast_response_always_labels": ["answer"],
            "fast_response_field_rules": [{"label": "answer", "markers": ["status"]}],
            "service_anchor_query_rewrites": [{"terms": ["sync"], "rewrite": "synchronize"}],
            "metadata_anchor_preflight_block_terms": ["ignore"],
            "question_anchor_bonus": 1.0,
            "boost_fields": [
                {"metadata": "topic", "weight": 2.0, "match": "contains"},
            ],
            "anchor_fields": [
                {
                    "metadata": "metadata.region",
                    "weight": 2.0,
                    "role": "administrative_area",
                    "aliases": {"emea": ["europe", "middle east"]},
                }
            ],
            "anchor_binding": {
                "enabled": True,
                "anchor_fields": ["metadata.region"],
                "slot_fields": ["topic"],
                "anchor_match_bonus": 1.5,
                "anchor_mismatch_penalty": 0.5,
                "slot_only_penalty": 0.5,
                "anchor_slot_match_bonus": 1.25,
            },
            "fallback": {"enabled": True, "expand_top_k_multiplier": 3},
            "response_compaction": {
                "enabled": True,
                "min_top_score": 0.4,
                "relative_score_floor": 0.25,
                "min_records": 2,
            },
            "response_hints": {
                "answer_prefix": "Answer:",
                "source_prefix": "Source:",
                "structured_labels": ["answer"],
                "answer_labels": ["answer"],
                "answer_keywords": ["resolved"],
                "answer_highlight_metadata": ["topic"],
                "answer_highlight_metadata_fields": [
                    {
                        "metadata": "topic",
                        "field": "topic",
                        "label": "Topic",
                        "fields": ["topic"],
                        "labels": {"topic": "Topic"},
                        "max_chars": 120,
                        "when_metadata": {"metadata.region": "emea"},
                        "metadata_when": {"topic": "billing"},
                        "prioritize_query_fields": True,
                        "requested_labels_prefix": "Need:",
                        "requested_labels_separator": ", ",
                    }
                ],
                "existing_hint_prefixes": ["Hint:"],
                "anchor_only_chunk_kinds": ["summary"],
                "anchor_only_markers": ["region-only"],
                "groups": [
                    {
                        "name": "answers",
                        "required_any_labels": ["answer"],
                        "hint_labels": ["source"],
                        "question_from_query_label": "question",
                        "answer_label": "answer",
                        "query_gate": {
                            "content_labels": ["answer"],
                            "metadata": ["topic"],
                            "min_chars": 3,
                            "min_common_chars": 2,
                        },
                    }
                ],
                "enumeration": {
                    "enabled": True,
                    "intro_terms": ["consider"],
                    "query_terms": ["options"],
                    "max_terms": 3,
                    "named_markers": {"primary": "1."},
                    "prefix": "Items:",
                    "message_template": "{items}",
                    "term_separator": ", ",
                },
            },
        },
        metadata_schema=_metadata_schema(),
    )


def test_validate_retrieval_policy_metadata_fields_rejects_non_filterable_fields() -> None:
    with pytest.raises(
        PipelinePluginContractError,
        match="retrieval_policy.filter_fields references non-filterable metadata fields: metadata.account_id",
    ):
        validate_retrieval_policy_metadata_fields(
            retrieval_policy={
                "schema": "mimirq.retrieval_policy.v1",
                "filter_fields": ["metadata.account_id"],
            },
            metadata_schema=_metadata_schema(),
        )


def test_validate_retrieval_policy_metadata_fields_rejects_empty_condition_field_names() -> None:
    with pytest.raises(
        PipelinePluginContractError,
        match=(
            "retrieval_policy.response_hints.answer_highlight_metadata_fields"
            r"\[0\]\.when_metadata contains an empty metadata field"
        ),
    ):
        validate_retrieval_policy_metadata_fields(
            retrieval_policy={
                "schema": "mimirq.retrieval_policy.v1",
                "response_hints": {
                    "answer_highlight_metadata_fields": [
                        {
                            "metadata": "topic",
                            "when_metadata": {"": "billing"},
                        }
                    ]
                },
            },
            metadata_schema=_metadata_schema(),
        )


def test_build_metadata_schema_views_builds_stage_scoped_views_and_record_identity() -> None:
    views = build_metadata_schema_views(
        Document(
            page_content="body",
            metadata={
                "topic": "billing",
                "metadata": {
                    "region": "emea",
                    "account_id": "acct-123",
                    "country": "de",
                    "chunk_kind": "summary",
                },
                "governance_only": "hidden",
            },
        ),
        metadata_schema=_metadata_schema(),
        stage="chunking",
    )

    assert views == {
        INDEXED_METADATA_KEY: {
            "topic": "billing",
            "metadata.region": "emea",
            "metadata.country": "de",
            "metadata.chunk_kind": "summary",
        },
        DISPLAY_METADATA_KEY: {
            "topic": "billing",
            "metadata.region": "emea",
            "metadata.account_id": "acct-123",
        },
        EVALUABLE_METADATA_KEY: {
            "topic": "billing",
            "metadata.account_id": "acct-123",
        },
        RECORD_IDENTITY_METADATA_KEY: {
            "schema": "mimirq.record_identity.v1",
            "key": "metadata.account_id=acct-123|topic=billing",
            "fields": {
                "metadata.account_id": "acct-123",
                "topic": "billing",
            },
        },
    }

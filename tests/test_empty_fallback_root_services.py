from uuid import uuid4

import pytest

from app.models.evaluation import RagasRegressionCase, RagasRegressionItem, RagasRegressionRun
from app.services import (
    cross_dataset_dedup_report,
    parser_strategy_policy,
    prompt_defaults,
    queryset_health_diff_service,
    rag_config_template_apply,
    rag_config_template_defaults,
    rag_config_template_resolver,
    regression_case_bundle,
    regression_run_bundle,
)


@pytest.mark.parametrize("provider", [0, False])
def test_patch_validation_does_not_mask_invalid_provider_types(provider: object) -> None:
    with pytest.raises(AttributeError):
        rag_config_template_apply.validate_rag_config_patch({"reranker_provider": provider})


@pytest.mark.parametrize("value", [0, False])
def test_prompt_defaults_does_not_replace_invalid_provided_keys(value: object) -> None:
    with pytest.raises(AttributeError):
        prompt_defaults.merge_prompt_defaults_with_dataset(
            prompt_template_id=None,
            prompt_template_key=value,
            prompt_ab_experiment_key=None,
            request_fields_set=set(),
            dataset_meta={"default_prompt_template_key": "fallback"},
        )


@pytest.mark.parametrize("value", [0, False])
def test_rag_template_defaults_does_not_replace_invalid_provided_keys(value: object) -> None:
    with pytest.raises(AttributeError):
        rag_config_template_defaults.merge_rag_config_template_defaults_with_dataset(
            rag_config_template_id=None,
            rag_config_template_key=value,
            rag_config_ab_experiment_key=None,
            request_fields_set=set(),
            dataset_meta={"default_rag_config_template_key": "fallback"},
        )


def test_queryset_diff_preserves_unavailable_report_facts() -> None:
    result = queryset_health_diff_service.diff_queryset_health_snapshots({}, {})
    assert result["baseline_generated_at"] is None
    assert result["policy"]["baseline_source"] is None
    assert result["policy"]["baseline_hash"] is None


def test_cross_dataset_report_requires_a_real_dataset_id() -> None:
    with pytest.raises(KeyError, match="dataset_id"):
        cross_dataset_dedup_report.build_cross_dataset_dedup_report([{"dataset_name": "dataset"}])


def test_cross_dataset_report_rejects_a_null_dataset_id() -> None:
    with pytest.raises(ValueError, match="dataset_id"):
        cross_dataset_dedup_report.build_cross_dataset_dedup_report([{"dataset_id": None}])


def test_case_export_preserves_supplied_scalar_reasoning_steps() -> None:
    dataset_id = uuid4()
    case = RagasRegressionCase(
        dataset_id=dataset_id, question="question", extra={"reasoning_hops": [0, False, None, "step"]}
    )
    result = regression_case_bundle.export_case_bundle([case], dataset_id)
    assert result["items"][0]["reasoning_hops"] == ["0", "False", "step"]


def test_run_export_rejects_missing_required_response() -> None:
    run = RagasRegressionRun(id=uuid4(), tenant_id=uuid4(), dataset_id=uuid4(), status="running")
    item = RagasRegressionItem(case_id=uuid4(), question="question", response=None)
    with pytest.raises(TypeError):
        regression_run_bundle.export_regression_run_bundle(run, [item], include_text=True)


def test_run_export_preserves_a_real_empty_response() -> None:
    run = RagasRegressionRun(id=uuid4(), tenant_id=uuid4(), dataset_id=uuid4(), status="running")
    item = RagasRegressionItem(case_id=uuid4(), question="question", response="")
    result = regression_run_bundle.export_regression_run_bundle(run, [item], include_text=True)
    assert result["items"][0]["response"] == ""
    assert result["items"][0]["response_chars"] == 0


def test_parser_recommendation_keeps_missing_profile_hints_unknown() -> None:
    result = parser_strategy_policy.recommend_parser_strategy(None)
    assert result["strategy"] == "generic_balanced"
    assert result["profile"]["mime_type"] is None
    assert result["profile"]["file_extension"] is None


@pytest.mark.parametrize("value", [0, False, 1, True])
def test_parser_recommendation_preserves_supported_scalar_hints(value: object) -> None:
    result = parser_strategy_policy.recommend_parser_strategy({"mime_type": value})
    assert result["profile"]["mime_type"] == str(value).lower()


def test_routing_writeback_does_not_invent_execution_facts() -> None:
    result = rag_config_template_resolver.build_adaptive_routing_reward_writeback(
        experiment_key=None, variant=None, strategy=None, decision=None, request_id=None
    )
    assert result["experiment_key"] is None
    assert result["strategy"] is None
    assert result["decision"] is None
    assert result["request_id"] is None

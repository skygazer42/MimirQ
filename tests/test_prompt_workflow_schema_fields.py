from __future__ import annotations


def test_testgen_request_exposes_prompt_selector_fields() -> None:
    from app.api.schemas.evaluation import TestGenFromDocsRequest

    assert "prompt_template_id" in TestGenFromDocsRequest.model_fields
    assert "prompt_template_key" in TestGenFromDocsRequest.model_fields
    assert "prompt_ab_experiment_key" in TestGenFromDocsRequest.model_fields


def test_regression_run_request_exposes_judge_prompt_selector_fields() -> None:
    from app.api.schemas.regression import RagasRegressionRunCreateRequest

    assert "judge_prompt_template_id" in RagasRegressionRunCreateRequest.model_fields
    assert "judge_prompt_template_key" in RagasRegressionRunCreateRequest.model_fields
    assert "judge_prompt_ab_experiment_key" in RagasRegressionRunCreateRequest.model_fields

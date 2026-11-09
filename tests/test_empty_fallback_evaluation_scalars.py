import importlib

import pytest

from app.rag.evaluation.datasets.schema import normalize_eval_dataset_sample
from app.rag.evaluation.metrics.answer_det import evaluate_answer_deterministic
from app.rag.evaluation.metrics.decomposition import compute_decomposition_metrics
from app.rag.evaluation.poc_runner import png_tasks


@pytest.mark.parametrize(
    "module_name",
    [
        "datasets.schema",
        "hard_negative_mining",
        "poc_runner.attribution_classifier",
        "poc_runner.out_of_scope_verifier",
        "poc_runner.source_builder",
        "poc_runner.telemetry",
    ],
)
@pytest.mark.parametrize("value", [0, False])
def test_nullable_scalar_text_preserves_provided_falsy_values(module_name, value):
    module = importlib.import_module(f"app.rag.evaluation.{module_name}")
    assert module._safe_str(value) == str(value)
    assert module._safe_str(None) is None


@pytest.mark.parametrize("value", [0, False])
def test_answer_metric_scores_provided_falsy_scalar(value):
    metrics = evaluate_answer_deterministic(
        question="What is the value?",
        answer=value,
        gold_answer=str(value),
        is_unanswerable=False,
    )
    assert metrics["answer_em"] == 1.0
    assert metrics["answer_f1"] == 1.0


@pytest.mark.parametrize("value", [0, False])
def test_subquery_metric_counts_provided_falsy_scalar(value):
    metrics = compute_decomposition_metrics(
        [{"gold_subqueries": [str(value)], "predicted_subqueries": [value]}]
    )
    assert metrics["decomposition_f1"] == 1.0


def test_dataset_normalization_preserves_missing_values_for_validation():
    row = normalize_eval_dataset_sample({})
    assert row["sample_id"] is None
    assert row["query"] is None
    assert row["gold_answer"] is None


def test_dataset_identifier_lists_keep_zero_and_false():
    row = normalize_eval_dataset_sample(
        {"gold_chunk_ids": [None, 0, False], "parent_sample_ids": [0, False], "tags": [0, False]}
    )
    assert row["gold_chunk_ids"] == ["0", "False"]
    assert row["parent_sample_ids"] == ["0", "False"]
    assert row["tags"] == ["0", "False"]


def test_png_task_missing_scope_cannot_match_blank_caller_scope():
    with pytest.raises(KeyError):
        png_tasks._scope_matches({}, tenant_id="", dataset_id="")


def test_png_task_missing_owner_remains_invalid():
    with pytest.raises(KeyError):
        png_tasks._task_account_id({})


def test_png_task_zero_scope_is_not_rewritten_to_blank():
    assert not png_tasks._scope_matches({"tenant_id": 0, "dataset_id": False}, tenant_id="", dataset_id="")


def test_png_task_missing_status_remains_invalid():
    with pytest.raises(KeyError):
        png_tasks._is_stale({})

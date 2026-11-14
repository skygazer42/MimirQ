import asyncio
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.rag.evaluation import (
    agent_evals,
    agent_redteam,
    judge_calibration,
    kg_hardcase_generator,
    llm_judge,
    test_generator,
)
from app.rag.evaluation.embedding_bench.runner import run_embedding_benchmark
from app.rag.evaluation.poc_runner.coverage_heatmap import build_document_heatmap
from app.rag.evaluation.poc_runner.reports.html_renderer import render_dataset_analysis_html
from app.rag.evaluation.recall_at_k_runner import run_recall_at_k_runner
from app.rag.evaluation.runners.hybrid_runner import _actual_answer_text


@pytest.mark.parametrize("value", [0, False])
def test_embedding_benchmark_scores_falsy_identifiers(value):
    report = run_embedding_benchmark(
        benchmark_name="scalar IDs",
        cases=[{"query_id": str(value), "query": "value", "expected_document_ids": [value]}],
        model_runs={"model": {"retrievals": {str(value): [value]}}},
    )
    assert report["models"][0]["summary"]["recall_at_k_mean"] == 1.0


@pytest.mark.parametrize("value", [0, False])
def test_recall_benchmark_scores_falsy_identifiers(value):
    report = run_recall_at_k_runner(
        [{"query_id": "q", "query": "value", "expected_document_ids": [value], "retrieved_document_ids": [value]}],
        top_k=1,
        benchmark_name="scalar IDs",
    )
    assert report["summary"]["recall_at_k_mean"] == 1.0


@pytest.mark.parametrize("value", [0, False])
def test_boundary_text_keeps_falsy_scalars(value):
    assert llm_judge.clip_text(value) == str(value)
    assert llm_judge.clip_contexts_for_judge([None, value]) == [str(value)]
    assert agent_redteam._iter_text([None, value]) == [str(value)]
    hardcases = kg_hardcase_generator.sanitize_hardcases(
        {"hardcases": [{"kind": "reasoning_pressure"}, {"kind": "knowledge_pressure", "question": value}]},
        max_items=5,
        max_chars=100,
    )
    assert [row.question for row in hardcases] == [str(value)]


@pytest.mark.parametrize("value", [0, False])
def test_document_heatmap_keeps_provided_falsy_filename(value):
    result = build_document_heatmap([{"final_context_filenames": [None, value]}])
    assert result["y_axis"] == [str(value)]


@pytest.mark.parametrize("value", [0, False])
def test_hybrid_answer_does_not_fall_through_provided_falsy_value(value):
    assert _actual_answer_text({"actual_answer": value, "answer": "other"}) == str(value)
    assert _actual_answer_text({"actual_answer": {"text": value}}) == str(value)


@pytest.mark.parametrize(
    ("factory", "arguments"),
    [
        (agent_evals.FaithfulnessEvaluator, ("q", "answer", ["answer"])),
        (agent_evals.RelevanceEvaluator, ("q", "answer")),
        (agent_evals.AnswerCorrectnessEvaluator, ("q", "answer", "answer")),
    ],
)
def test_incomplete_llm_score_uses_existing_observable_heuristic_path(factory, arguments):
    class MissingExplanationLLM:
        async def ainvoke(self, prompt):
            return SimpleNamespace(content='{"score": 0.123}')

    evaluator = factory(MissingExplanationLLM())
    result = asyncio.run(evaluator._llm_evaluate(*arguments))
    assert result.score != 0.123
    assert result.explanation


def test_testgen_drops_invalid_items_and_preserves_valid_siblings():
    result = {"questions": [None, {}, {"question": []}, {"question": "valid", "expected_answer": "answer"}]}
    rows = test_generator._normalize_testgen_result_rows(result)
    assert [row["question"] for row in rows] == ["valid"]
    questions = test_generator._conversation_generated_questions(result)
    assert [row.question for row in questions] == ["valid"]
    assert questions[0].metadata["original_question"] is None
    assert "source_id" not in questions[0].metadata


def test_judge_prompt_selection_forwards_provided_spaces(monkeypatch):
    calls = []

    def resolve(**kwargs):
        calls.append(kwargs)
        return None

    monkeypatch.setattr(llm_judge, "resolve_prompt_template", resolve)
    llm_judge._resolve_generation_judge_prompt(
        db=object(), tenant_id=uuid4(), template_id=None, template_key="  ", ab_experiment_key=None, ab_user_key=None
    )
    assert calls[0]["template_key"] == "  "


def test_calibration_rejects_malformed_required_version_type():
    with pytest.raises(ValueError, match="calibration_dataset_version_required"):
        judge_calibration.validate_calibration_payload(
            {
                "schema": judge_calibration.CALIBRATION_SCHEMA,
                "judge_version_hash": "judge-v1",
                "dataset_version": True,
                "label_policy_version": "policy-v1",
                "items": [
                    {
                        "case_id": "case",
                        "human_label": "supported",
                        "judge_label": "supported",
                        "reviewer_hash": "reviewer-hash",
                        "reviewed_at": "2026-11-09T00:00:00Z",
                    }
                ],
            },
            min_items=1,
        )


def test_html_report_displays_provided_falsy_values():
    report = render_dataset_analysis_html(
        {
            "meta": {"generated_at": "2026-11-09"},
            "metric_cards": [{"key": 0, "value": False}],
            "top_examples": {"example": [{"interaction_id": 0, "original_query": False}]},
        }
    )
    assert "<code>0</code>" in report
    assert "<strong>0</strong> False" in report


def test_single_redteam_case_keeps_absent_optional_identifier():
    result = agent_redteam.evaluate_agent_redteam_case({"scenario": "memory_poisoning", "memory_writes": []})
    assert result["case_id"] is None
    assert result["passed"] is True

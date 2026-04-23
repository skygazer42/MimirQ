from __future__ import annotations

import pytest

from app.rag.evaluation.hard_negative_stress import evaluate_hard_negative_case, run_hard_negative_stress


def test_evaluate_hard_negative_case_flags_entity_match_but_fact_mismatch() -> None:
    result = evaluate_hard_negative_case(
        {
            "case_id": "hn-001",
            "query": "华发股份董事会有多少位董事？",
            "answer": "华发股份董事会有 9 位董事。",
            "gold_answer": "华发股份董事会有 14 位董事。",
            "citations": [{"chunk_id": "chunk-a"}],
        }
    )

    assert result["schema"] == "mimirq.hard_negative_case.v1"
    assert result["case_id"] == "hn-001"
    assert result["passed"] is False
    assert result["hard_negative_triggered"] is True
    assert result["reason_codes"] == ["hard_negative_triggered"]
    assert result["answer_f1"] == pytest.approx(0.9, abs=1e-4)


def test_evaluate_hard_negative_case_passes_exact_match_answer() -> None:
    result = evaluate_hard_negative_case(
        {
            "case_id": "hn-002",
            "query": "485 怎么配置？",
            "answer": "参考 RS-485 配置流程。",
            "gold_answer": "参考 RS-485 配置流程。",
            "citations": [{"chunk_id": "chunk-b"}],
        }
    )

    assert result["passed"] is True
    assert result["hard_negative_triggered"] is False
    assert result["reason_codes"] == []


def test_run_hard_negative_stress_aggregates_failure_rate() -> None:
    summary = run_hard_negative_stress(
        [
            {
                "case_id": "hn-001",
                "query": "华发股份董事会有多少位董事？",
                "answer": "华发股份董事会有 9 位董事。",
                "gold_answer": "华发股份董事会有 14 位董事。",
                "citations": [{"chunk_id": "chunk-a"}],
            },
            {
                "case_id": "hn-002",
                "query": "485 怎么配置？",
                "answer": "参考 RS-485 配置流程。",
                "gold_answer": "参考 RS-485 配置流程。",
                "citations": [{"chunk_id": "chunk-b"}],
            },
        ]
    )

    assert summary["schema"] == "mimirq.hard_negative_stress_summary.v1"
    assert summary["total_cases"] == 2
    assert summary["failed_cases"] == 1
    assert summary["pass_rate"] == pytest.approx(0.5)
    assert summary["avg_answer_f1"] == pytest.approx(0.95)

from __future__ import annotations

import pytest

from app.rag.evaluation.ragcap_bench_runner import evaluate_ragcap_case, run_ragcap_bench


def test_evaluate_ragcap_case_scores_agentic_intermediate_capabilities() -> None:
    result = evaluate_ragcap_case(
        {
            "case_id": "ragcap-001",
            "query_type": "multi_hop",
            "expected": {
                "plan_steps": ["找 485 参数", "确认 watchdog 时间"],
                "tools": ["semantic_search", "chunk_read"],
                "reflection_needed": True,
                "termination": "completed",
            },
            "trace": {
                "plan_steps": [
                    {"query": "找 485 参数"},
                    {"query": "确认 watchdog 时间"},
                ],
                "tool_calls": [
                    {"name": "semantic_search"},
                    {"name": "chunk_read"},
                ],
                "intermediate_claims": [
                    {"supported": True},
                    {"supported": False},
                    {"supported": True},
                ],
                "reflection": {"triggered": True},
                "termination": {"status": "completed"},
            },
        }
    )

    assert result["schema"] == "mimirq.ragcap_case_result.v1"
    assert result["case_id"] == "ragcap-001"
    assert result["metrics"]["plan_correctness"] == 1.0
    assert result["metrics"]["tool_selection_accuracy"] == 1.0
    assert result["metrics"]["intermediate_factuality"] == 0.6667
    assert result["metrics"]["reflection_trigger_precision"] == 1.0
    assert result["metrics"]["termination_correctness"] == 1.0
    assert result["overall_score"] == 0.9333
    assert result["passed"] is True
    assert result["reason_codes"] == []


def test_evaluate_ragcap_case_emits_reason_codes_for_mismatched_trace() -> None:
    result = evaluate_ragcap_case(
        {
            "case_id": "ragcap-002",
            "query_type": "factual",
            "expected": {
                "plan_steps": ["定位协议字段"],
                "tools": ["keyword_search"],
                "reflection_needed": False,
                "termination": "completed",
            },
            "trace": {
                "plan_steps": [{"query": "随机发散"}],
                "tool_calls": [{"name": "web_search"}],
                "intermediate_claims": [{"supported": False}],
                "reflection": {"triggered": True},
                "termination": {"status": "failed"},
            },
        }
    )

    assert result["passed"] is False
    assert result["overall_score"] == 0.0
    assert result["reason_codes"] == [
        "plan_incorrect",
        "tool_selection_mismatch",
        "intermediate_factuality_low",
        "reflection_mismatch",
        "termination_incorrect",
    ]


def test_run_ragcap_bench_aggregates_case_metrics_and_pass_rate() -> None:
    summary = run_ragcap_bench(
        [
            {
                "case_id": "ragcap-001",
                "expected": {
                    "plan_steps": ["a"],
                    "tools": ["semantic_search"],
                    "reflection_needed": False,
                    "termination": "completed",
                },
                "trace": {
                    "plan_steps": [{"query": "a"}],
                    "tool_calls": [{"name": "semantic_search"}],
                    "intermediate_claims": [{"supported": True}],
                    "reflection": {"triggered": False},
                    "termination": {"status": "completed"},
                },
            },
            {
                "case_id": "ragcap-002",
                "expected": {
                    "plan_steps": ["b"],
                    "tools": ["keyword_search"],
                    "reflection_needed": True,
                    "termination": "completed",
                },
                "trace": {
                    "plan_steps": [{"query": "c"}],
                    "tool_calls": [{"name": "web_search"}],
                    "intermediate_claims": [{"supported": False}],
                    "reflection": {"triggered": False},
                    "termination": {"status": "failed"},
                },
            },
        ]
    )

    assert summary["schema"] == "mimirq.ragcap_bench_summary.v1"
    assert summary["total_cases"] == 2
    assert summary["passed_cases"] == 1
    assert summary["pass_rate"] == 0.5
    assert summary["metrics"]["plan_correctness"] == 0.5
    assert summary["metrics"]["tool_selection_accuracy"] == 0.5
    assert summary["metrics"]["intermediate_factuality"] == 0.5
    assert summary["metrics"]["reflection_trigger_precision"] == 0.5
    assert summary["metrics"]["termination_correctness"] == 0.5
    assert summary["metrics"]["overall_score"] == pytest.approx(0.5, abs=1e-4)

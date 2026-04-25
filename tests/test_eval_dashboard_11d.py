from __future__ import annotations


def test_summarize_eval_dashboard_11d_aggregates_dimensions_and_slices() -> None:
    from app.rag.evaluation.reports.dashboard_11d import summarize_eval_dashboard_11d

    rows = [
        {
            "sample_id": "s1",
            "route_id": "retrieval",
            "query_type": "factual",
            "expected_route": "retrieval",
            "actual_route": "retrieval",
            "latency_ms": 1000,
            "token_cost": 0.10,
            "evaluators": {
                "answer_det": {"answer_em": 1.0, "answer_f1": 1.0, "refusal_correct": None},
                "retrieval": {"recall_at_k": 1.0, "citation_coverage": 1.0, "citation_precision": 1.0, "mrr": 1.0},
                "faithfulness": {"score": 0.9},
            },
            "retrieval_trace": {"schema": "mimirq.retrieval_trace.v1"},
        },
        {
            "sample_id": "s2",
            "route_id": "hybrid",
            "query_type": "multi_hop",
            "expected_route": "hybrid",
            "actual_route": "hybrid",
            "latency_ms": 1500,
            "token_cost": 0.20,
            "evaluators": {
                "answer_det": {"answer_em": 0.0, "answer_f1": 0.5, "refusal_correct": None},
                "retrieval": {"recall_at_k": 0.5, "citation_coverage": 0.5, "citation_precision": 0.5, "mrr": 0.4},
                "fusion": {"conflict_rate": 1.0, "net_gain_over_best_single": 0.1},
                "faithfulness": {"score": 0.8},
            },
            "extensions": {
                "gold_subqueries": ["find company", "count directors"],
                "predicted_subqueries": ["find company", "board count"],
                "hard_negative_recall_drop": 0.2,
            },
        },
        {
            "sample_id": "s3",
            "route_id": "retrieval",
            "query_type": "unanswerable",
            "expected_route": "retrieval",
            "actual_route": "retrieval",
            "latency_ms": 800,
            "token_cost": 0.05,
            "evaluators": {
                "answer_det": {"answer_em": 0.0, "answer_f1": 0.0, "refusal_correct": True},
                "retrieval": {"recall_at_k": 0.0, "citation_coverage": 0.0, "citation_precision": 0.0, "mrr": 0.0},
                "faithfulness": {"score": 1.0},
            },
        },
    ]

    out = summarize_eval_dashboard_11d(rows)

    assert out["schema"] == "mimirq.eval.dashboard_11d.v1"
    assert out["summary"]["sample_count"] == 3
    assert out["summary"]["route_ids"] == ["hybrid", "retrieval"]

    dims = out["dimensions"]
    assert dims["routing_decision"]["routing_accuracy"] == 1.0
    assert dims["routing_decision"]["decomposition_f1"] == 0.5
    assert dims["retrieval_quality"]["recall_at_k_avg"] == 0.5
    assert dims["fusion_quality"]["conflict_rate"] == 1.0
    assert dims["answer_quality"]["answer_f1_avg"] == 0.5
    assert dims["citation_quality"]["citation_coverage_avg"] == 0.5
    assert dims["abstain_ability"]["abstain_rate"] == 1.0
    assert dims["interference_resilience"]["hard_negative_recall_drop_avg"] == 0.2
    assert dims["latency"]["p50_ms"] == 1000.0
    assert dims["cost"]["cost_per_correct"] == 0.175
    assert dims["explainability"]["decision_trace_coverage"] == 0.3333

    by_type = out["by_query_type"]
    assert by_type["factual"]["sample_count"] == 1
    assert by_type["multi_hop"]["sample_count"] == 1
    assert by_type["unanswerable"]["sample_count"] == 1


def test_summarize_eval_dashboard_11d_reports_stability_from_repeated_samples() -> None:
    from app.rag.evaluation.reports.dashboard_11d import summarize_eval_dashboard_11d

    rows = [
        {
            "sample_id": "repeat-1",
            "route_id": "retrieval",
            "query_type": "factual",
            "latency_ms": 1000,
            "token_cost": 0.1,
            "evaluators": {"answer_det": {"answer_em": 1.0, "answer_f1": 1.0}},
        },
        {
            "sample_id": "repeat-1",
            "route_id": "retrieval",
            "query_type": "factual",
            "latency_ms": 1200,
            "token_cost": 0.1,
            "evaluators": {"answer_det": {"answer_em": 0.0, "answer_f1": 0.5}},
        },
    ]

    out = summarize_eval_dashboard_11d(rows)
    stability = out["dimensions"]["stability"]

    assert stability["sample_groups_with_repeats"] == 1
    assert stability["latency_ms_std_avg"] == 100.0
    assert stability["answer_f1_std_avg"] == 0.25

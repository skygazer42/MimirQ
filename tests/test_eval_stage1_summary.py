from __future__ import annotations

from app.rag.evaluation.reports.stage1_summary import summarize_stage1_results


def test_summarize_stage1_results_aggregates_and_slices_by_query_type() -> None:
    summary = summarize_stage1_results(
        [
            {
                "route_id": "retrieval",
                "query_type": "factual",
                "expected_route": "retrieval",
                "actual_route": "retrieval",
                "latency_ms": 1000,
                "token_cost": 0.1,
                "citations": [{"chunk_id": "c1"}],
                "evaluators": {
                    "answer_det": {"answer_em": 1.0, "answer_f1": 1.0, "refusal_correct": None},
                    "retrieval": {"recall_at_k": 1.0, "citation_coverage": 1.0},
                },
            },
            {
                "route_id": "hybrid",
                "query_type": "structured",
                "expected_route": "kg",
                "actual_route": "hybrid",
                "latency_ms": 1400,
                "token_cost": 0.2,
                "citations": [{"chunk_id": "c2"}],
                "evaluators": {
                    "answer_det": {"answer_em": 0.0, "answer_f1": 0.5, "refusal_correct": None},
                    "retrieval": {"recall_at_k": 0.5, "citation_coverage": 0.5},
                    "routing": {"routing_accuracy": 0.0},
                    "fusion": {"conflict_rate": 1.0, "net_gain_over_best_single": 0.0},
                },
            },
        ]
    )

    assert summary["overall"]["sample_count"] == 2
    assert summary["overall"]["route_ids"] == ["hybrid", "retrieval"]
    assert summary["overall"]["latency_ms_avg"] == 1200.0
    assert summary["by_query_type"]["factual"]["sample_count"] == 1
    assert summary["by_query_type"]["structured"]["sample_count"] == 1

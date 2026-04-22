from __future__ import annotations

from app.rag.evaluation.results.schema import EVAL_RESULT_SCHEMA_V1, normalize_eval_result_row


def test_normalize_eval_result_row_preserves_common_fields_and_agentic_placeholders() -> None:
    row = normalize_eval_result_row(
        {
            "sample_id": "s1",
            "route_id": "retrieval",
            "query_type": "factual",
            "source_type": "real_log",
            "expected_route": "retrieval",
            "actual_route": "retrieval",
            "answer": {"text": "ok"},
            "citations": [{"chunk_id": "chunk-1"}],
            "latency_ms": 1200,
            "token_cost": 0.12,
            "route_config": {"top_k": 10},
            "evaluators": {"answer_det": {"answer_em": 1.0}},
        }
    )

    assert row["schema_version"] == EVAL_RESULT_SCHEMA_V1
    assert row["route_id"] == "retrieval"
    assert row["route_config"]["top_k"] == 10
    assert row["agentic_iterations"] is None
    assert row["agentic_latency_ms"] is None
    assert row["agentic_token_cost"] is None
    assert row["agentic_status"] is None

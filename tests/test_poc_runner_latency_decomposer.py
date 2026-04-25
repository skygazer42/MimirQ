from __future__ import annotations

from app.rag.evaluation.poc_runner.latency_decomposer import decompose_latency_rows


def test_decompose_latency_rows_separates_queue_and_active_inference() -> None:
    payload = decompose_latency_rows(
        [
            {
                "interaction_id": "req-1",
                "latency_total_ms": 8000,
                "retrieval_elapsed_sec": 1.5,
                "generation_elapsed_sec": 2.5,
                "prompt_tokens": 400,
                "completion_tokens": 100,
            }
        ]
    )

    assert payload["schema"] == "mimirq.poc.latency_decomposer.v1"
    row = payload["rows"][0]
    assert row["interaction_id"] == "req-1"
    assert row["active_inference_ms"] == 4000
    assert row["wait_in_queue_ms"] == 4000
    assert row["model_prefill_ms"] == 2000
    assert row["model_decode_ms"] == 500
    assert row["bottleneck"] == "concurrency_issue"


def test_decompose_latency_rows_flags_hardware_when_active_inference_dominates() -> None:
    payload = decompose_latency_rows(
        [
            {
                "interaction_id": "req-2",
                "latency_total_ms": 4200,
                "retrieval_elapsed_sec": 0.8,
                "generation_elapsed_sec": 3.0,
                "prompt_tokens": 200,
                "completion_tokens": 300,
            }
        ]
    )

    row = payload["rows"][0]
    assert row["wait_in_queue_ms"] == 400
    assert row["bottleneck"] == "hardware_or_model_issue"
    assert payload["summary"]["hardware_or_model_issue_count"] == 1

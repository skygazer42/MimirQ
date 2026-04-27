from __future__ import annotations

from app.rag.evaluation.recall_at_k_runner import run_recall_at_k_runner


def test_run_recall_at_k_runner_summarizes_hit_rate_mrr_latency_and_cost() -> None:
    out = run_recall_at_k_runner(
        [
            {
                "query_id": "q1",
                "query": "如何配置 MQTT 连接？",
                "expected_document_ids": ["doc-a"],
                "retrieved_document_ids": ["doc-a", "doc-b"],
                "latency_ms": 120,
                "cost_usd": 0.01,
            },
            {
                "query_id": "q2",
                "query": "授权失效怎么办？",
                "expected_document_ids": ["doc-c"],
                "retrieved_document_ids": ["doc-x", "doc-c"],
                "latency_ms": 80,
                "cost_usd": 0.0,
            },
        ],
        top_k=2,
        benchmark_name="poc-30q-mini",
    )

    assert out["schema"] == "mimirq.recall_at_k_runner.v1"
    assert out["benchmark_name"] == "poc-30q-mini"
    assert out["summary"]["query_count"] == 2
    assert out["summary"]["recall_at_k_mean"] == 1.0
    assert out["summary"]["mrr_mean"] == 0.75
    assert out["summary"]["avg_latency_ms"] == 100.0
    assert out["summary"]["avg_cost_usd"] == 0.005
    assert out["rows"][1]["mrr"] == 0.5


def test_run_recall_at_k_runner_handles_misses() -> None:
    out = run_recall_at_k_runner(
        [
            {
                "query_id": "q-miss",
                "expected_document_ids": ["doc-a"],
                "retrieved_document_ids": ["doc-x", "doc-y"],
            }
        ],
        top_k=2,
        benchmark_name="poc-miss",
    )

    assert out["summary"]["recall_at_k_mean"] == 0.0
    assert out["summary"]["mrr_mean"] == 0.0
    assert out["rows"][0]["hit_at_k"] == 0.0

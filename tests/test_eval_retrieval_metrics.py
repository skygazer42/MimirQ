from __future__ import annotations

from app.rag.evaluation.metrics.retrieval import evaluate_retrieval_metrics


def test_evaluate_retrieval_metrics_reports_recall_and_citation_coverage() -> None:
    metrics = evaluate_retrieval_metrics(
        gold_chunk_ids=["c1", "c2"],
        retrieved_chunk_ids=["c9", "c1", "c7"],
        cited_chunk_ids=["c1"],
        recall_k=3,
    )

    assert metrics["recall_at_k"] == 0.5
    assert metrics["citation_coverage"] == 0.5

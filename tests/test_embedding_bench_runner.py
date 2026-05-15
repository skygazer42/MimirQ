from __future__ import annotations


def test_embedding_benchmark_summarizes_models_and_selects_best() -> None:
    from app.rag.evaluation.embedding_bench.runner import run_embedding_benchmark

    report = run_embedding_benchmark(
        benchmark_name="mini-embedding-golden",
        top_k=2,
        cases=[
            {"query_id": "q1", "query": "alpha", "expected_document_ids": ["doc-a"]},
            {"query_id": "q2", "query": "beta", "expected_document_ids": ["doc-c"]},
        ],
        model_runs={
            "openai/text-embedding-3-small": {
                "retrievals": {
                    "q1": ["doc-b", "doc-a"],
                    "q2": ["doc-x", "doc-y"],
                },
                "latency_ms": {"q1": 12.0, "q2": 14.0},
                "cost_usd": {"q1": 0.001, "q2": 0.001},
            },
            "local/BAAI/bge-m3": {
                "retrievals": {
                    "q1": ["doc-a", "doc-b"],
                    "q2": ["doc-c", "doc-y"],
                },
                "latency_ms": {"q1": 8.0, "q2": 10.0},
                "cost_usd": {"q1": 0.0, "q2": 0.0},
            },
        },
    )

    assert report["schema"] == "mimirq.embedding_benchmark.v1"
    assert report["benchmark_name"] == "mini-embedding-golden"
    assert report["best_model_id"] == "local/BAAI/bge-m3"

    rows = {row["model_id"]: row for row in report["models"]}
    assert rows["openai/text-embedding-3-small"]["summary"] == {
        "query_count": 2,
        "hit_at_k_mean": 0.5,
        "recall_at_k_mean": 0.5,
        "mrr_mean": 0.25,
        "avg_latency_ms": 13.0,
        "total_cost_usd": 0.002,
    }
    assert rows["local/BAAI/bge-m3"]["summary"]["recall_at_k_mean"] == 1.0
    assert rows["local/BAAI/bge-m3"]["rows"][0]["retrieved_document_ids"] == ["doc-a", "doc-b"]


def test_embedding_benchmark_can_rank_corpus_from_embeddings() -> None:
    from app.rag.evaluation.embedding_bench.runner import rank_corpus_by_cosine

    ranked = rank_corpus_by_cosine(
        query_embedding=[1.0, 0.0],
        corpus_embeddings={
            "doc-left": [1.0, 0.0],
            "doc-up": [0.0, 1.0],
            "doc-near": [0.8, 0.2],
        },
        top_k=2,
    )

    assert ranked == ["doc-left", "doc-near"]

from __future__ import annotations


def test_summarize_fusion_weight_observability_counts_rrf_and_ltr_ready_rows() -> None:
    from app.services.fusion_weight_learning_service import summarize_fusion_weight_observability

    rows = [
        {
            "event": "rag_trace",
            "tenant_id": "t1",
            "retrieval": {
                "per_query": [
                    {
                        "retriever_debug": {
                            "channels": {
                                "fusion_strategy": "rrf",
                                "rrf_k": 60,
                                "fusion_weights": {"vector": 0.7, "bm25": 0.3},
                            }
                        }
                    }
                ]
            },
            "citations": [
                {"vector_score": 0.8, "bm25_score": 0.2, "lexical_score": 0.0, "sparse_score": 0.0},
                {"vector_score": 0.4, "bm25_score": 0.5, "lexical_score": 0.3, "sparse_score": 0.1},
            ],
        },
        {
            "schema": "mimirq.training_export_row.v1",
            "dataset_id": "ds1",
            "source_type": "feedback",
            "reference_sources": [{"document_id": "doc-pos", "chunk_id": "chunk-pos"}],
            "trace_snapshot": {
                "event": "rag_trace",
                "tenant_id": "t1",
                "retrieval": {
                    "per_query": [
                        {
                            "retriever_debug": {
                                "channels": {
                                    "fusion_strategy": "weighted",
                                    "rrf_k": 90,
                                    "fusion_weights": {"vector": 0.5, "bm25": 0.2, "lexical": 0.2, "sparse": 0.1},
                                }
                            }
                        }
                    ]
                },
                "citations": [
                    {"document_id": "doc-pos", "chunk_id": "chunk-pos", "vector_score": 0.9, "bm25_score": 0.1},
                ],
            },
        },
    ]

    out = summarize_fusion_weight_observability(rows, tenant_id="t1")

    assert out["schema"] == "mimirq.fusion_weight_observability.v1"
    assert out["tenant_id"] == "t1"
    assert out["summary"]["observed_rows"] == 2
    assert out["summary"]["ltr_training_ready_rows"] == 1
    assert out["summary"]["rrf_k_histogram"] == {"60": 1, "90": 1}
    assert out["summary"]["fusion_strategy_histogram"] == {"rrf": 1, "weighted": 1}
    assert out["summary"]["channel_signal_coverage"]["vector"] == 3


def test_suggest_tenant_fusion_weights_prefers_channels_with_better_positive_separation() -> None:
    from app.services.fusion_weight_learning_service import suggest_tenant_fusion_weights

    rows = [
        {
            "schema": "mimirq.training_export_row.v1",
            "source_type": "feedback",
            "reference_sources": [{"document_id": "doc-pos", "chunk_id": "chunk-pos"}],
            "trace_snapshot": {
                "tenant_id": "t1",
                "citations": [
                    {
                        "document_id": "doc-pos",
                        "chunk_id": "chunk-pos",
                        "vector_score": 0.95,
                        "bm25_score": 0.20,
                        "lexical_score": 0.15,
                        "sparse_score": 0.10,
                    },
                    {
                        "document_id": "doc-neg",
                        "chunk_id": "chunk-neg",
                        "vector_score": 0.30,
                        "bm25_score": 0.45,
                        "lexical_score": 0.40,
                        "sparse_score": 0.20,
                    },
                ]
            },
        },
        {
            "schema": "mimirq.training_export_row.v1",
            "source_type": "feedback",
            "reference_sources": [{"document_id": "doc-pos-2", "chunk_id": "chunk-pos-2"}],
            "trace_snapshot": {
                "tenant_id": "t1",
                "citations": [
                    {
                        "document_id": "doc-pos-2",
                        "chunk_id": "chunk-pos-2",
                        "vector_score": 0.88,
                        "bm25_score": 0.10,
                        "lexical_score": 0.10,
                        "sparse_score": 0.05,
                    },
                    {
                        "document_id": "doc-neg-2",
                        "chunk_id": "chunk-neg-2",
                        "vector_score": 0.25,
                        "bm25_score": 0.35,
                        "lexical_score": 0.33,
                        "sparse_score": 0.12,
                    },
                ]
            },
        },
    ]

    out = suggest_tenant_fusion_weights(rows, tenant_id="t1", min_rows=2)

    assert out["schema"] == "mimirq.tenant_fusion_weights.v1"
    assert out["tenant_id"] == "t1"
    assert out["summary"]["training_rows"] == 2
    weights = out["fusion_weights"]
    assert round(sum(weights.values()), 6) == 1.0
    assert weights["vector"] > weights["bm25"]
    assert weights["vector"] > weights["lexical"]
    assert out["summary"]["weight_source"] == "feedback_trace_snapshot"

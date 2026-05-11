from __future__ import annotations


def test_regression_item_model_has_meta_column():
    from app.models.evaluation import RagasRegressionItem

    assert hasattr(RagasRegressionItem, "meta")


def test_runtime_migrations_include_regression_item_meta():
    from pathlib import Path

    text = Path("app/core/migrations.py").read_text(encoding="utf-8")
    assert "ALTER TABLE ragas_regression_items ADD COLUMN IF NOT EXISTS meta JSONB" in text


def test_build_regression_item_meta_includes_ids_and_abstain_fields():
    from app.rag.evaluation.regression_sample_builder import build_regression_item_meta

    meta = build_regression_item_meta(
        sample_kwargs={
            "reference_context_ids": ["ref-1", "ref-2"],
            "retrieved_context_ids": ["got-1"],
        },
        item_meta={
            "abstain_triggered": True,
            "abstain_reason": "citations_lt_min",
            "top_relevance_score": 0.12,
        },
    )

    assert meta == {
        "reference_context_ids": ["ref-1", "ref-2"],
        "retrieved_context_ids": ["got-1"],
        "slice_file_type": None,
        "slice_language": None,
        "slice_directory": None,
        "slice_hit_type": None,
        "slice_modality": None,
        "slice_quality_bucket": None,
        "slice_parse_quality": None,
        "slice_chunk_quality": None,
        "slice_pipeline_hash": None,
        "multimodal_router": None,
        "golden_multimodal_slice": None,
        "tag_meta": None,
        "image_meta": None,
        "abstain_triggered": True,
        "abstain_reason": "citations_lt_min",
        "top_relevance_score": 0.12,
        "retrieval_recall": None,
        "retrieval_hit": None,
        "retrieval_mrr": None,
        "retrieval_ndcg_at_10": None,
        "retrieval_ndcg_at_20": None,
        "retrieval_hit_at_1": None,
        "retrieval_hit_at_3": None,
        "retrieval_hit_at_5": None,
        "retrieval_hit_at_10": None,
        "retrieval_hit_at_20": None,
        "faithfulness_det": None,
        "citation_accuracy": None,
        "citation_coverage": None,
        "hallucination_rate": None,
        "quote_verifiability": None,
        "atomic_faithfulness": None,
        "chunk_utilization": None,
        "chunk_attribution": None,
        "noise_sensitivity": None,
        "self_knowledge_ratio": None,
        "chunk_diag_counts": None,
        "explanations": None,
        "expected_refusal": None,
        "refusal_correct": None,
        "llm_judge": None,
    }

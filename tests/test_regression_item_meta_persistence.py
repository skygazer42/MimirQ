

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
        "retrieval_doc_recall": None,
        "retrieval_doc_hit": None,
        "retrieval_family_recall": None,
        "retrieval_family_hit": None,
        "must_recall_passed": None,
        "must_recall_status": None,
        "evidence_capsule": None,
        "provenance_integrity_passed": None,
        "provenance_integrity_status": None,
        "faithfulness_det": None,
        "citation_accuracy": None,
        "citation_coverage": None,
        "citation_eval_limit": None,
        "citation_total_count": None,
        "citation_evaluated_count": None,
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


def test_build_regression_item_meta_preserves_effective_context_metrics():
    from app.rag.evaluation.regression_sample_builder import build_regression_item_meta

    meta = build_regression_item_meta(
        sample_kwargs={},
        item_meta={
            "retrieval_effective_context_rate": 0.75,
            "retrieval_noise_rate": 0.25,
            "retrieval_effective_records": 3,
            "retrieval_evaluated_records": 4,
        },
    )

    assert meta["retrieval_effective_context_rate"] == 0.75
    assert meta["retrieval_noise_rate"] == 0.25
    assert meta["retrieval_effective_records"] == 3
    assert meta["retrieval_evaluated_records"] == 4


def test_build_regression_item_meta_preserves_retrieval_audit_fields():
    from app.rag.evaluation.regression_sample_builder import build_regression_item_meta

    capsule = {
        "schema": "mimirq.evidence_capsule.v1",
        "capsule_hash": "capsule-123",
        "citations": [{"citation_hash": "cit-1"}],
    }
    meta = build_regression_item_meta(
        sample_kwargs={},
        item_meta={
            "retrieval_doc_recall": 1.0,
            "retrieval_doc_hit": True,
            "retrieval_family_recall": 1.0,
            "retrieval_family_hit": True,
            "must_recall_passed": True,
            "must_recall_status": "passed",
            "evidence_capsule": capsule,
            "provenance_integrity_passed": True,
            "provenance_integrity_status": "passed",
            "parse_quality_alert": False,
            "parse_risk_level": "low",
        },
    )

    assert meta["retrieval_doc_recall"] == 1.0
    assert meta["retrieval_doc_hit"] is True
    assert meta["retrieval_family_recall"] == 1.0
    assert meta["retrieval_family_hit"] is True
    assert meta["must_recall_passed"] is True
    assert meta["must_recall_status"] == "passed"
    assert meta["evidence_capsule"] == capsule
    assert meta["provenance_integrity_passed"] is True
    assert meta["provenance_integrity_status"] == "passed"
    assert meta["parse_quality_alert"] is False
    assert meta["parse_risk_level"] == "low"

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
        "abstain_triggered": True,
        "abstain_reason": "citations_lt_min",
        "top_relevance_score": 0.12,
    }


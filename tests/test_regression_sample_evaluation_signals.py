from __future__ import annotations

from types import SimpleNamespace


def test_regression_sample_builder_emits_citation_and_hallucination_signals() -> None:
    from app.rag.evaluation.regression_sample_builder import build_regression_item_meta, build_regression_sample

    case = SimpleNamespace(
        expected_answer="Alpha is the approved policy.",
        reference_sources=[
            {
                "document_id": "doc-1",
                "chunk_id": "chunk-1",
                "quote": "Alpha is the approved policy.",
            }
        ],
        extra={},
    )
    item = {
        "question": "What is the approved policy?",
        "response": 'Alpha is the approved policy. "Alpha is the approved policy."',
        "retrieved_contexts": ["Alpha is the approved policy."],
        "citations": [
            {
                "document_id": "doc-1",
                "chunk_id": "chunk-1",
                "chunk_content": "Alpha is the approved policy.",
            }
        ],
    }

    sample_kwargs, meta = build_regression_sample(case, item)
    stored_meta = build_regression_item_meta(sample_kwargs=sample_kwargs, item_meta=meta)

    assert meta["citation_accuracy"] == 1.0
    assert meta["citation_coverage"] == 1.0
    assert meta["quote_verifiability"] == 1.0
    assert meta["atomic_faithfulness"] == 1.0
    assert meta["hallucination_rate"] == 0.0
    assert stored_meta["citation_accuracy"] == 1.0
    assert stored_meta["quote_verifiability"] == 1.0

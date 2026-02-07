from __future__ import annotations


def test_regression_retrieval_metrics_match_by_doc_pipeline_key_and_chunk_index():
    from app.rag.evaluation.regression_sample_builder import build_regression_sample

    case = {
        "expected_answer": None,
        "reference_sources": [
            {
                "document_id": "doc-1",
                "chunk_id": "stale-chunk-id",
                "doc_pipeline_key": "doc-1:ph1",
                "pipeline_hash": "ph1",
                "chunk_index": 2,
                "quote": "alpha beta gamma",
            }
        ],
    }
    item = {
        "question": "what is alpha",
        "response": "",
        "retrieved_contexts": [],
        "citations": [
            {
                "document_id": "doc-1",
                "chunk_id": "new-chunk-id",
                "doc_pipeline_key": "doc-1:ph1",
                "pipeline_hash": "ph1",
                "chunk_index": 2,
                "chunk_content": "alpha beta gamma",
            }
        ],
    }

    _sample_kwargs, meta = build_regression_sample(case, item)
    assert meta["retrieval_recall"] == 1.0
    assert meta["retrieval_hit"] is True
    assert meta["retrieval_mrr"] == 1.0
    assert meta["retrieval_hit_at_1"] is True


def test_regression_retrieval_metrics_match_by_quote_signature_when_ids_change():
    from app.rag.evaluation.regression_sample_builder import build_regression_sample

    quote = "A very specific phrase that should survive chunk-id changes."
    case = {
        "expected_answer": None,
        "reference_sources": [
            {
                "document_id": "doc-1",
                "chunk_id": "stale-chunk-id",
                "quote": quote,
            }
        ],
    }
    item = {
        "question": "what phrase",
        "response": "",
        "retrieved_contexts": [],
        "citations": [
            {
                "document_id": "doc-1",
                "chunk_id": "new-chunk-id",
                "chunk_content": f"... {quote} ...",
            }
        ],
    }

    _sample_kwargs, meta = build_regression_sample(case, item)
    assert meta["retrieval_recall"] == 1.0
    assert meta["retrieval_hit"] is True
    assert meta["retrieval_mrr"] == 1.0


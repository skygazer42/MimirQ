from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4


def test_build_regression_sample_includes_reference_context_ids_and_abstain_meta():
    from app.rag.evaluation.regression_sample_builder import build_regression_sample  # noqa: WPS433

    ds = uuid4()
    doc_id = uuid4()
    ref_chunk_a = uuid4()
    ref_chunk_b = uuid4()
    got_chunk_a = ref_chunk_a
    got_chunk_b = uuid4()

    case = SimpleNamespace(
        dataset_id=ds,
        expected_answer=None,
        reference_sources=[
            {"document_id": str(doc_id), "chunk_id": str(ref_chunk_a), "quote": "ref a"},
            {"document_id": str(doc_id), "chunk_id": str(ref_chunk_b), "quote": "ref b"},
        ],
    )

    item = {
        "case_id": str(uuid4()),
        "question": "q",
        "response": "a",
        "retrieved_contexts": ["ctx a", "ctx b"],
        "citations": [{"chunk_id": str(got_chunk_a)}, {"chunk_id": str(got_chunk_b)}, {"chunk_id": str(got_chunk_a)}],
        "abstain_triggered": True,
        "abstain_reason": "citations_lt_min",
        "top_relevance_score": 0.12,
    }

    sample_kwargs, meta = build_regression_sample(case, item)

    assert sample_kwargs["user_input"] == "q"
    assert sample_kwargs["response"] == "a"
    assert sample_kwargs["reference"] == ""  # expected_answer None -> empty string
    assert sample_kwargs["reference_context_ids"] == [str(ref_chunk_a), str(ref_chunk_b)]
    assert sample_kwargs["retrieved_context_ids"] == [str(got_chunk_a), str(got_chunk_b)]
    assert sample_kwargs["reference_contexts"] == ["ref a", "ref b"]

    assert meta == {
        "abstain_triggered": True,
        "abstain_reason": "citations_lt_min",
        "top_relevance_score": 0.12,
        "retrieval_recall": 0.5,
        "retrieval_hit": True,
        "retrieval_mrr": 1.0,
        "retrieval_ndcg_at_10": 0.6131,
        "retrieval_hit_at_1": True,
        "retrieval_hit_at_3": True,
        "retrieval_hit_at_5": True,
        "retrieval_hit_at_10": True,
    }

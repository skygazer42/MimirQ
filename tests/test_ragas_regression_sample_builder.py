from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4


def test_build_regression_sample_includes_reference_context_ids_and_abstain_meta():
    from app.rag.core.hashing import stable_hash
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
        "citations": [
            {"chunk_id": str(got_chunk_a), "document_id": str(doc_id)},
            {"chunk_id": str(got_chunk_b), "document_id": str(doc_id)},
            {"chunk_id": str(got_chunk_a), "document_id": str(doc_id)},
        ],
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

    missed_b = stable_hash(str(ref_chunk_b), length=16)

    assert meta == {
        "abstain_triggered": True,
        "abstain_reason": "citations_lt_min",
        "top_relevance_score": 0.12,
        "retrieval_recall": 0.5,
        "retrieval_hit": True,
        "retrieval_mrr": 1.0,
        "retrieval_ndcg_at_10": 0.6131,
        "retrieval_ndcg_at_20": 0.6131,
        "retrieval_hit_at_1": True,
        "retrieval_hit_at_3": True,
        "retrieval_hit_at_5": True,
        "retrieval_hit_at_10": True,
        "retrieval_hit_at_20": True,
        "retrieval_doc_recall": 1.0,
        "retrieval_doc_hit": True,
        "retrieval_family_recall": None,
        "retrieval_family_hit": None,
        "faithfulness_det": 1.0,
        "citation_accuracy": 0.5,
        "citation_coverage": 0.5,
        "hallucination_rate": 0.0,
        "quote_verifiability": None,
        "atomic_faithfulness": 1.0,
        "chunk_utilization": None,
        "chunk_attribution": None,
        "noise_sensitivity": None,
        "self_knowledge_ratio": None,
        "chunk_diag_counts": {
            "claims_total": 0,
            "claims_supported": 0,
            "claims_noisy": 0,
            "claims_correct_total": 0,
            "claims_correct_uncited": 0,
            "chunks_total": 2,
            "chunks_used": 0,
        },
        "explanations": {
            "chunk_utilization": "chunks_used=0/2",
            "citation_accuracy": "relevant_citations=1/2",
            "retrieval_recall": f"ref_sources=2, matched=1, missed=1, missed_ids=['{missed_b}']",
        },
        "expected_refusal": None,
        "reasoning_hops_count": 0,
        "evidence_chain_steps": 0,
        "multihop_enabled": False,
        "multihop_path_completeness": None,
        "multihop_order_consistency": None,
        "multihop_chain_hit": None,
    }

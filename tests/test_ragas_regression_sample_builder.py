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


def test_build_regression_sample_limits_citation_precision_to_eval_window():
    from app.rag.evaluation.regression_sample_builder import build_regression_sample  # noqa: WPS433

    doc_id = uuid4()
    ref_chunk = uuid4()
    noise_chunk_a = uuid4()
    noise_chunk_b = uuid4()
    noise_chunk_c = uuid4()

    case = SimpleNamespace(
        expected_answer=None,
        reference_sources=[
            {"document_id": str(doc_id), "chunk_id": str(ref_chunk), "quote": "ref a"},
        ],
    )
    item = {
        "question": "q",
        "response": "",
        "retrieved_contexts": ["ctx"] * 4,
        "citation_eval_limit": 2,
        "citations": [
            {"chunk_id": str(ref_chunk), "document_id": str(doc_id)},
            {"chunk_id": str(noise_chunk_a), "document_id": str(doc_id)},
            {"chunk_id": str(noise_chunk_b), "document_id": str(doc_id)},
            {"chunk_id": str(noise_chunk_c), "document_id": str(doc_id)},
        ],
    }

    sample_kwargs, meta = build_regression_sample(case, item)

    assert sample_kwargs["retrieved_context_ids"] == [str(ref_chunk), str(noise_chunk_a)]
    assert meta["retrieval_recall"] == 1.0
    assert meta["retrieval_hit_at_1"] is True
    assert meta["citation_accuracy"] == 0.5
    assert meta["citation_total_count"] == 4
    assert meta["citation_evaluated_count"] == 2
    assert meta["citation_eval_limit"] == 2
    assert meta["explanations"]["citation_accuracy"] == "relevant_citations=1/2, evaluated_top=2, total=4"


def test_build_regression_sample_scores_effective_contexts_from_answer_key_points():
    from app.rag.evaluation.regression_sample_builder import build_regression_sample  # noqa: WPS433

    doc_id = uuid4()
    ref_chunk = uuid4()
    noise_chunk = uuid4()

    case = SimpleNamespace(
        expected_answer="Alpha permit requires identity proof.",
        reference_sources=[
            {"document_id": str(doc_id), "chunk_id": str(ref_chunk), "quote": "Alpha permit requires identity proof."},
        ],
        extra={
            "answer_key_points": ["identity proof"],
            "answer_key_point_aliases": {"identity proof": ["ID proof"]},
        },
    )
    item = {
        "question": "What does the alpha permit require?",
        "response": "",
        "retrieved_contexts": ["Alpha permit requires ID proof.", "Alpha permit office hours."],
        "citation_eval_limit": 2,
        "citations": [
            {
                "chunk_id": str(ref_chunk),
                "document_id": str(doc_id),
                "chunk_content": "Alpha permit snippet.",
            },
            {
                "chunk_id": str(noise_chunk),
                "document_id": str(doc_id),
                "chunk_content": "Alpha permit office hours.",
            },
        ],
    }

    _sample_kwargs, meta = build_regression_sample(case, item)

    assert meta["citation_accuracy"] == 0.5
    assert meta["retrieval_effective_context_rate"] == 0.5
    assert meta["retrieval_noise_rate"] == 0.5
    assert meta["retrieval_effective_records"] == 1
    assert meta["retrieval_evaluated_records"] == 2
    assert meta["explanations"]["retrieval_effective_context_rate"] == "effective_records=1/2"


def test_build_regression_sample_counts_semantic_key_overlap_as_retrieval_hit():
    from app.rag.evaluation.regression_sample_builder import build_regression_sample  # noqa: WPS433

    doc_id = uuid4()
    case = SimpleNamespace(
        expected_answer="Broad FAQ answer.",
        reference_sources=[
            {
                "document_id": str(doc_id),
                "chunk_id": "reference-chunk",
                "quote": "Broad FAQ answer.",
                "semantic_keys": ["faq:birth-registration", "alias:birth-permit"],
            }
        ],
        extra={
            "expected_metadata": {
                "semantic_keys": ["faq:birth-registration", "alias:birth-permit"],
                "gov_knowledge_type": "qa",
            },
        },
    )
    item = {
        "question": "birth permit",
        "response": "",
        "retrieved_contexts": ["District FAQ answer."],
        "citation_eval_limit": 1,
        "citations": [
            {
                "chunk_id": "semantic-equivalent-chunk",
                "document_id": str(uuid4()),
                "chunk_content": "District FAQ answer.",
                "metadata": {
                    "semantic_keys": ["alias:birth-permit", "faq:district-birth-permit"],
                    "_evaluable_metadata": {
                        "gov_knowledge_type": "qa",
                    }
                },
            }
        ],
    }

    _sample_kwargs, meta = build_regression_sample(case, item)

    assert meta["retrieval_recall"] == 1.0
    assert meta["retrieval_hit_at_1"] is True
    assert meta["citation_accuracy"] == 1.0
    assert meta["expected_metadata_hit"] is True
    assert meta["expected_metadata_recall"] == 1.0


def test_build_regression_sample_uses_expected_semantic_keys_when_reference_lacks_them():
    from app.rag.evaluation.regression_sample_builder import build_regression_sample  # noqa: WPS433

    doc_id = uuid4()
    case = SimpleNamespace(
        expected_answer="Birth permit FAQ answer.",
        reference_sources=[
            {
                "document_id": str(doc_id),
                "chunk_id": "stale-reference-chunk",
                "quote": "Birth permit FAQ answer.",
            }
        ],
        extra={
            "expected_metadata": {
                "semantic_keys": ["intent:准生证", "alias:准生证"],
                "gov_knowledge_type": "qa",
            },
        },
    )
    item = {
        "question": "准生证",
        "response": "",
        "retrieved_contexts": ["Birth permit FAQ answer from an equivalent district chunk."],
        "citation_eval_limit": 1,
        "citations": [
            {
                "chunk_id": "semantic-equivalent-chunk",
                "document_id": str(uuid4()),
                "chunk_content": "Birth permit FAQ answer from an equivalent district chunk.",
                "metadata": {
                    "_evaluable_metadata": {
                        "semantic_keys": ["intent:准生证", "alias:准生证"],
                        "gov_knowledge_type": "qa",
                    }
                },
            }
        ],
    }

    _sample_kwargs, meta = build_regression_sample(case, item)

    assert meta["retrieval_recall"] == 1.0
    assert meta["retrieval_hit_at_1"] is True
    assert meta["citation_accuracy"] == 1.0
    assert meta["expected_metadata_hit"] is True


def test_build_regression_sample_ndcg_is_capped_for_duplicate_record_identity_hits():
    from app.rag.evaluation.regression_sample_builder import build_regression_sample  # noqa: WPS433

    record_identity = {
        "schema": "mimirq.record_identity.v1",
        "key": "source_record_id=record-1",
        "fields": {"source_record_id": "record-1"},
    }
    case = SimpleNamespace(
        expected_answer=None,
        reference_sources=[
            {
                "document_id": "doc-1",
                "chunk_id": "ref-chunk",
                "quote": "record answer",
                "_record_identity": record_identity,
            }
        ],
    )
    item = {
        "question": "q",
        "response": "",
        "retrieved_contexts": ["record answer", "record details"],
        "citations": [
            {"chunk_id": "chunk-a", "document_id": "doc-1", "_record_identity": record_identity},
            {"chunk_id": "chunk-b", "document_id": "doc-1", "_record_identity": record_identity},
        ],
    }

    _sample_kwargs, meta = build_regression_sample(case, item)

    assert meta["retrieval_recall"] == 1.0
    assert meta["citation_accuracy"] == 1.0
    assert meta["retrieval_ndcg_at_10"] == 1.0
    assert meta["retrieval_ndcg_at_20"] == 1.0

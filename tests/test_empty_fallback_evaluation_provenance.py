import asyncio

import pytest

from app.rag.evaluation.agent_evals import RAGEvaluator
from app.rag.evaluation.kg_search_diagnostics_metrics import compute_kg_hit_metrics
from app.rag.evaluation.multihop import score_multihop_citation_chain
from app.rag.evaluation.multimodal_slices import summarize_multimodal_regression_slices
from app.rag.evaluation.regression_sample_builder import build_regression_sample
from app.rag.evaluation.replay_capture import fingerprint_citations
from app.rag.evaluation.results.schema import normalize_eval_result_row


@pytest.mark.parametrize("value", [0, False])
def test_multihop_keeps_provided_falsy_identifier(value):
    result = score_multihop_citation_chain(
        evidence_chain=[{"chunk_id": str(value)}], citations=[{"chunk_id": value}]
    )
    assert result["path_completeness"] == 1.0


@pytest.mark.parametrize("value", [0, False])
def test_kg_hit_metrics_keep_provided_falsy_identifier(value):
    result = compute_kg_hit_metrics(evidence_chunk_ids={str(value)}, events=[{"chunk_id": value}], k=5)
    assert result["hit_at_k"] == 1.0


@pytest.mark.parametrize("value", [0, False])
def test_regression_reference_document_recall_preserves_falsy_identifier(value):
    _, meta = build_regression_sample(
        {"reference_sources": [{"chunk_id": "ref", "document_id": str(value)}]},
        {"question": "q", "response": "answer", "citations": [{"chunk_id": "hit", "document_id": value}]},
    )
    assert meta["retrieval_doc_recall"] == 1.0


@pytest.mark.parametrize("value", [0, False])
def test_multimodal_coverage_counts_provided_falsy_context(value):
    result = summarize_multimodal_regression_slices([{"retrieved_contexts": [value]}])
    assert result["evaluatable"]["text"] == 1


@pytest.mark.parametrize("value", [0, False])
def test_replay_fingerprint_distinguishes_present_scalar_from_blank(value):
    assert fingerprint_citations([{"chunk_id": value}]) != fingerprint_citations([{"chunk_id": ""}])


def test_regression_missing_response_remains_invalid():
    with pytest.raises(KeyError):
        build_regression_sample({}, {"question": "q"})


def test_regression_missing_reference_remains_absent():
    sample, _ = build_regression_sample({}, {"question": "q", "response": "answer"})
    assert sample["reference"] is None


def test_evaluation_missing_sample_identity_remains_invalid():
    with pytest.raises(KeyError):
        normalize_eval_result_row({"route_id": "retrieval", "query_type": "factual", "source_type": "real_log"})


def test_agent_evaluation_missing_question_remains_invalid():
    with pytest.raises(KeyError):
        asyncio.run(RAGEvaluator().evaluate_batch([{"answer": "answer"}]))

from __future__ import annotations

from app.rag.evaluation.multihop import score_multihop_citation_chain
from app.rag.evaluation.regression_sample_builder import build_regression_sample


def test_score_multihop_citation_chain_perfect_path_and_order() -> None:
    out = score_multihop_citation_chain(
        evidence_chain=[
            {"chunk_id": "c1", "document_id": "d1"},
            {"chunk_id": "c2", "document_id": "d2"},
            {"chunk_id": "c3", "document_id": "d3"},
        ],
        citations=[
            {"chunk_id": "c1"},
            {"chunk_id": "c2"},
            {"chunk_id": "c3"},
        ],
        reasoning_hops=["hop1", "hop2", "hop3"],
        top_k=20,
    )
    assert out.get("schema") == "mimirq.multihop_chain_score.v1"
    assert out.get("enabled") is True
    assert float(out.get("path_completeness") or 0.0) == 1.0
    assert float(out.get("order_consistency") or 0.0) == 1.0
    assert out.get("chain_hit") is True


def test_score_multihop_citation_chain_partial_and_wrong_order() -> None:
    out = score_multihop_citation_chain(
        evidence_chain=[
            {"chunk_id": "c1", "document_id": "d1"},
            {"chunk_id": "c2", "document_id": "d2"},
            {"chunk_id": "c3", "document_id": "d3"},
        ],
        citations=[
            {"chunk_id": "c2"},
            {"chunk_id": "c1"},
        ],
        reasoning_hops=["hop1", "hop2", "hop3"],
        top_k=20,
    )
    assert float(out.get("path_completeness") or 0.0) == 0.6667
    assert float(out.get("order_consistency") or 0.0) == 0.0
    assert out.get("chain_hit") is False
    assert "c3" in list(out.get("missing_chain_ids") or [])


def test_build_regression_sample_emits_multihop_meta_fields() -> None:
    class _Case:
        expected_answer = "x"
        reference_sources = [{"chunk_id": "c1", "document_id": "d1"}]
        reasoning_hops = ["find parent", "resolve child"]
        evidence_chain = [
            {"chunk_id": "c1", "document_id": "d1"},
            {"chunk_id": "c2", "document_id": "d2"},
        ]
        extra = {}

    _sample, meta = build_regression_sample(
        _Case(),
        {
            "question": "q",
            "response": "r",
            "retrieved_contexts": [],
            "citations": [{"chunk_id": "c1"}, {"chunk_id": "c2"}],
        },
    )
    assert meta.get("reasoning_hops_count") == 2
    assert meta.get("evidence_chain_steps") == 2
    assert meta.get("multihop_enabled") is True
    assert float(meta.get("multihop_path_completeness") or 0.0) == 1.0

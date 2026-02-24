from __future__ import annotations

from app.rag.evaluation.evidence_retrieve_gate import (  # noqa: F401
    build_retrieval_gate_summary,
    compute_retrieval_item_meta,
)


def test_compute_retrieval_item_meta_matches_by_chunk_id() -> None:
    case = {
        "reference_sources": [
            {
                "chunk_id": "chunk-1",
                "doc_pipeline_key": "doc-1:h",
                "chunk_index": 7,
                "quote": "Refund policy: annual plans are refundable within 30 days.",
            }
        ]
    }
    citations = [
        {"chunk_id": "chunk-1", "doc_pipeline_key": "doc-1:h", "chunk_index": 7, "chunk_content": "Refund policy..."},
        {"chunk_id": "chunk-2", "doc_pipeline_key": "doc-1:h", "chunk_index": 8, "chunk_content": "Noise..."},
    ]

    meta = compute_retrieval_item_meta(case=case, citations=citations)
    assert meta["retrieval_recall"] == 1.0
    assert meta["retrieval_mrr"] == 1.0
    assert meta["retrieval_hit_at_1"] is True
    assert meta["retrieval_hit_at_10"] is True


def test_compute_retrieval_item_meta_matches_by_pipeline_key_and_chunk_index_when_chunk_id_drifts() -> None:
    case = {
        "reference_sources": [
            {
                "chunk_id": "old-chunk-id",
                "doc_pipeline_key": "doc-1:h",
                "chunk_index": 7,
                "quote": "Refund policy: annual plans are refundable within 30 days.",
            }
        ]
    }
    citations = [
        {
            "chunk_id": "new-chunk-id",
            "doc_pipeline_key": "doc-1:h",
            "chunk_index": 7,
            "chunk_content": "Refund policy...",
        }
    ]

    meta = compute_retrieval_item_meta(case=case, citations=citations)
    assert meta["retrieval_recall"] == 1.0
    assert meta["retrieval_mrr"] == 1.0
    assert meta["retrieval_hit_at_1"] is True


def test_build_retrieval_gate_summary_aggregates_items() -> None:
    items = [
        {"retrieval_recall": 1.0, "retrieval_hit_at_10": True, "abstain_triggered": False},
        {"retrieval_recall": 0.0, "retrieval_hit_at_10": False, "abstain_triggered": True},
    ]

    summary = build_retrieval_gate_summary(items)
    assert summary["retrieval_recall"] == 0.5
    assert summary["retrieval_hit_at_10"] == 0.5
    assert summary["abstain_rate"] == 0.5


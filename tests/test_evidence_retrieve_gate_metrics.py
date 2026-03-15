from __future__ import annotations

import pytest

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
    assert meta["retrieval_recall"] == pytest.approx(1.0)
    assert meta["retrieval_mrr"] == pytest.approx(1.0)
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
    assert meta["retrieval_recall"] == pytest.approx(1.0)
    assert meta["retrieval_mrr"] == pytest.approx(1.0)
    assert meta["retrieval_hit_at_1"] is True


def test_compute_retrieval_item_meta_includes_parse_slo_fields_from_metrics() -> None:
    meta = compute_retrieval_item_meta(
        case={"reference_sources": []},
        citations=[],
        retrieval_metrics={
            "parse_quality_alert": True,
            "parse_quality_low_ratio": 0.7,
            "parse_risk_level": "high",
            "parse_risk_score": 0.9,
            "parse_quality_gate_profile": "strict",
            "parse_quality_gate_blocked": True,
            "evidence_capsule": {
                "schema": "mimirq.evidence_capsule.v1",
                "capsule_hash": "abc123",
                "citations": [{"citation_hash": "c1"}],
            },
        },
    )
    assert meta["parse_quality_alert"] is True
    assert float(meta["parse_quality_low_ratio"]) == pytest.approx(0.7)
    assert str(meta["parse_risk_level"]) == "high"
    assert float(meta["parse_risk_score"]) == pytest.approx(0.9)
    assert str(meta["parse_quality_gate_profile"]) == "strict"
    assert meta["parse_quality_gate_blocked"] is True
    assert meta["provenance_integrity_passed"] is True


def test_build_retrieval_gate_summary_aggregates_items() -> None:
    items = [
        {
            "retrieval_recall": 1.0,
            "retrieval_hit_at_10": True,
            "abstain_triggered": False,
            "must_recall_passed": True,
            "parse_quality_alert": False,
            "parse_quality_gate_blocked": False,
            "parse_risk_level": "low",
            "parse_risk_score": 0.1,
            "provenance_integrity_passed": True,
        },
        {
            "retrieval_recall": 0.0,
            "retrieval_hit_at_10": False,
            "abstain_triggered": True,
            "must_recall_passed": False,
            "parse_quality_alert": True,
            "parse_quality_gate_blocked": True,
            "parse_risk_level": "high",
            "parse_risk_score": 0.9,
            "provenance_integrity_passed": False,
        },
    ]

    summary = build_retrieval_gate_summary(items)
    assert summary["retrieval_recall"] == pytest.approx(0.5)
    assert summary["retrieval_hit_at_10"] == pytest.approx(0.5)
    assert summary["abstain_rate"] == pytest.approx(0.5)
    assert summary["must_recall_pass_rate"] == pytest.approx(0.5)
    assert summary["must_recall_cases_total"] == 2
    assert summary["parse_quality_alert_rate"] == pytest.approx(0.5)
    assert summary["parse_quality_gate_block_rate"] == pytest.approx(0.5)
    assert summary["parse_risk_high_cases"] == 1
    assert summary["parse_risk_high_rate"] == pytest.approx(0.5)
    assert summary["provenance_integrity_rate"] == pytest.approx(0.5)
    assert summary["provenance_cases_total"] == 2

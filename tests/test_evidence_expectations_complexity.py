
from typing import Any

from app.rag.core.evidence_expectations import evaluate_evidence_anchor_expectations


def test_evidence_expectations_tracks_skips_and_missing_examples() -> None:
    citations: Any = [
        {"chunk_id": "chunk-1", "document_id": "doc-1"},
        {"chunk_id": "", "document_id": "doc-2"},
        {"chunk_id": "chunk-3", "document_id": None},
        {"retrieval_role": "fallback:keyword", "chunk_id": "", "document_id": ""},
        "ignored",
    ]
    result = evaluate_evidence_anchor_expectations(
        citations=citations,
        required_fields=["Chunk_ID", "document_id", "chunk_id"],
        exclude_retrieval_role_prefixes=["fallback:"],
    )

    assert result == {
        "required_fields": ["chunk_id", "document_id"],
        "considered_citations": 3,
        "skipped_citations": 1,
        "skipped_by_role": {"fallback:keyword": 1},
        "missing_counts": {"chunk_id": 1, "document_id": 1},
        "missing_any": 2,
        "missing_examples": [
            {"chunk_id": "", "missing_fields": ["chunk_id"]},
            {"chunk_id": "chunk-3", "missing_fields": ["document_id"]},
        ],
        "passed": False,
    }


def test_evidence_expectations_without_required_fields_counts_raw_items() -> None:
    citations: Any = [{"chunk_id": "chunk-1"}, "not-a-dict"]
    result = evaluate_evidence_anchor_expectations(
        citations=citations,
        required_fields=[],
    )

    assert result["considered_citations"] == 2
    assert result["passed"] is True

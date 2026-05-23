from __future__ import annotations

from scripts.remote_governance_ingest_matrix import (
    citation_text_from_response,
    evaluate_case_expectations,
    metadata_has_nonempty_value,
)


def test_remote_governance_ingest_matrix_metadata_has_nonempty_value() -> None:
    assert metadata_has_nonempty_value({"hits": {"email": 1}}, "hits") is True
    assert metadata_has_nonempty_value({"count": 2}, "count") is True
    assert metadata_has_nonempty_value({"text": "[PII]"}, "text") is True
    assert metadata_has_nonempty_value({"hits": {}}, "hits") is False
    assert metadata_has_nonempty_value({"count": 0}, "count") is False
    assert metadata_has_nonempty_value({"text": ""}, "text") is False
    assert metadata_has_nonempty_value({}, "missing") is False


def test_remote_governance_ingest_matrix_citation_text_from_response_joins_common_fields() -> None:
    body = {
        "citations": [
            {"chunk_content": "masked [PII] chunk"},
            {"content": "second body"},
            {"text": "third text"},
            {"snippet": "fourth snippet"},
        ]
    }

    text = citation_text_from_response(body)

    assert "masked [PII] chunk" in text
    assert "second body" in text
    assert "third text" in text
    assert "fourth snippet" in text


def test_remote_governance_ingest_matrix_evaluate_case_expectations_accepts_sanitized_document() -> None:
    case = {
        "name": "pii_mask",
        "expected_status": "completed",
        "required_metadata_keys": ["governance_pii_hits"],
        "required_rule_packs": ["web_navigation"],
        "present_in_parsed": ["[PII]"],
        "absent_in_parsed": ["alice@example.com"],
        "present_in_chunks": ["[PII]"],
        "absent_in_chunks": ["alice@example.com"],
        "require_citations": True,
        "present_in_citations": ["[PII]"],
        "absent_in_citations": ["alice@example.com"],
    }

    failures = evaluate_case_expectations(
        case,
        document_status="completed",
        metadata={
            "governance_enabled": True,
            "governance_pii_hits": {"email": 1},
            "governance_rule_packs": ["web_navigation"],
        },
        parsed_text="Contact [PII] for rollout notes.",
        chunk_text="Contact [PII] for rollout notes.",
        citation_text="Contact [PII] for rollout notes.",
        citation_count=1,
    )

    assert failures == []


def test_remote_governance_ingest_matrix_evaluate_case_expectations_flags_quarantine_mismatches() -> None:
    case = {
        "name": "quality_gate_quarantine",
        "expected_status": "quarantined",
        "allowed_drop_reasons": ["low_density", "outline_only"],
        "required_metadata_keys": ["governance_dropped_documents"],
    }

    failures = evaluate_case_expectations(
        case,
        document_status="completed",
        metadata={"governance_enabled": True, "governance_drop_reasons": {"unexpected": 1}},
        parsed_text="",
        chunk_text="",
        citation_text="",
        citation_count=0,
    )

    assert any("status" in item for item in failures)
    assert any("governance_dropped_documents" in item for item in failures)
    assert any("drop_reasons" in item for item in failures)

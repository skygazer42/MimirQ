from __future__ import annotations

from scripts.remote_kb_boundary_matrix import (
    citation_document_ids,
    evaluate_boundary_case,
    exported_document_ids,
    response_text_from_body,
)


def test_remote_kb_boundary_matrix_exported_document_ids_reads_common_shapes() -> None:
    assert exported_document_ids({"documents": [{"id": "doc-a"}, {"document_id": "doc-b"}]}) == ["doc-a", "doc-b"]
    assert exported_document_ids({"items": [{"id": "doc-c"}]}) == ["doc-c"]
    assert exported_document_ids({"results": [{"document_id": "doc-d"}]}) == ["doc-d"]
    assert exported_document_ids({}) == []


def test_remote_kb_boundary_matrix_citation_document_ids_reads_common_shapes() -> None:
    body = {
        "citations": [
            {"document_id": "doc-a", "chunk_content": "Alpha owner Alice Meridian"},
            {"document_id": "doc-b", "content": "Beta owner Bob Quartz"},
        ]
    }

    assert citation_document_ids(body) == ["doc-a", "doc-b"]
    assert "Alice Meridian" in response_text_from_body(body)
    assert "Bob Quartz" in response_text_from_body(body)


def test_remote_kb_boundary_matrix_evaluate_boundary_case_accepts_in_scope_match() -> None:
    case = {
        "name": "dataset_alpha_positive",
        "allowed_document_ids": ["doc-alpha"],
        "expected_document_ids": ["doc-alpha"],
        "expected_terms": ["Alice Meridian", "ALOE-COMET"],
        "min_citations": 1,
    }

    failures = evaluate_boundary_case(
        case,
        citation_doc_ids=["doc-alpha"],
        citation_count=1,
        response_text="Alice Meridian owns token ALOE-COMET.",
    )

    assert failures == []


def test_remote_kb_boundary_matrix_evaluate_boundary_case_supports_required_document_subset() -> None:
    case = {
        "name": "cross_dataset_beta_positive",
        "allowed_document_ids": ["doc-alpha", "doc-beta"],
        "required_document_ids": ["doc-beta"],
        "expected_terms": ["BETA-QUARTZ"],
        "min_citations": 1,
    }

    failures = evaluate_boundary_case(
        case,
        citation_doc_ids=["doc-beta", "doc-alpha"],
        citation_count=2,
        response_text="BETA-QUARTZ belongs to doc-beta while doc-alpha is still in scope.",
    )

    assert failures == []


def test_remote_kb_boundary_matrix_evaluate_boundary_case_flags_missing_required_document_subset() -> None:
    case = {
        "name": "cross_dataset_beta_positive",
        "allowed_document_ids": ["doc-alpha", "doc-beta"],
        "required_document_ids": ["doc-beta"],
        "expected_terms": ["BETA-QUARTZ"],
        "min_citations": 1,
    }

    failures = evaluate_boundary_case(
        case,
        citation_doc_ids=["doc-alpha"],
        citation_count=1,
        response_text="BETA-QUARTZ was requested but only doc-alpha was cited.",
    )

    assert any("required_document_ids" in item for item in failures)


def test_remote_kb_boundary_matrix_evaluate_boundary_case_flags_leakage_and_missing_terms() -> None:
    case = {
        "name": "dataset_alpha_negative_beta_query",
        "allowed_document_ids": ["doc-alpha"],
        "expected_document_ids": [],
        "forbidden_terms": ["Bob Quartz", "BETA-QUARTZ"],
        "max_citations": 0,
    }

    failures = evaluate_boundary_case(
        case,
        citation_doc_ids=["doc-beta"],
        citation_count=1,
        response_text="Bob Quartz appears in BETA-QUARTZ.",
    )

    assert any("unexpected document_ids" in item for item in failures)
    assert any("max_citations" in item for item in failures)
    assert any("forbidden_terms" in item for item in failures)

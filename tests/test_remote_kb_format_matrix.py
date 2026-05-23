from __future__ import annotations

from scripts.remote_kb_format_matrix import evaluate_format_case


def test_remote_kb_format_matrix_case_accepts_expected_doc_and_terms() -> None:
    case = {
        "name": "word_project_brief_docx",
        "expected_document_id": "doc-word",
        "expected_terms": ["Lina Chen"],
        "min_chunks": 1,
        "min_parsed_chars": 20,
        "min_citations": 1,
    }

    failures = evaluate_format_case(
        case,
        document_id="doc-word",
        chunk_count=1,
        parsed_chars=120,
        citation_doc_ids=["doc-word"],
        citation_count=1,
        response_text="Lina Chen owns the rollout.",
    )

    assert failures == []


def test_remote_kb_format_matrix_case_flags_missing_terms_and_wrong_doc() -> None:
    case = {
        "name": "excel_budget_sheet_xlsx",
        "expected_document_id": "doc-xlsx",
        "expected_terms": ["Review"],
        "min_chunks": 1,
        "min_parsed_chars": 20,
        "min_citations": 1,
    }

    failures = evaluate_format_case(
        case,
        document_id="doc-xlsx",
        chunk_count=0,
        parsed_chars=0,
        citation_doc_ids=["doc-other"],
        citation_count=0,
        response_text="No answer.",
    )

    assert any("expected_document_id" in item for item in failures)
    assert any("min_chunks" in item for item in failures)
    assert any("min_parsed_chars" in item for item in failures)
    assert any("min_citations" in item for item in failures)
    assert any("expected_terms" in item for item in failures)

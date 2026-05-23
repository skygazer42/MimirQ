from __future__ import annotations

from scripts.remote_kb_permission_boundary import (
    evaluate_http_expectation,
    evaluate_permission_scope_case,
)


def test_remote_kb_permission_boundary_evaluate_http_expectation() -> None:
    assert evaluate_http_expectation("shared_export", 200, [200]) == []
    failures = evaluate_http_expectation("private_export", 200, [403])
    assert any("expected_statuses" in item for item in failures)


def test_remote_kb_permission_boundary_evaluate_permission_scope_case_accepts_filtered_scope() -> None:
    case = {
        "name": "outsider_mixed_scope_shared_query",
        "allowed_document_ids": ["doc-shared"],
        "expected_document_ids": ["doc-shared"],
        "expected_terms": ["ALOE-COMET"],
        "forbidden_terms": ["BETA-QUARTZ", "Bob Quartz"],
        "min_citations": 1,
    }

    failures = evaluate_permission_scope_case(
        case,
        citation_doc_ids=["doc-shared"],
        citation_count=1,
        response_text="Token ALOE-COMET belongs only to Dataset Alpha.",
    )

    assert failures == []

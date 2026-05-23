from __future__ import annotations

from scripts.remote_kb_permission_boundary import (
    document_access_summary,
    evaluate_http_expectation,
    evaluate_permission_scope_case,
    group_id_from_body,
    group_member_ids_from_body,
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


def test_remote_kb_permission_boundary_group_helpers_read_common_shapes() -> None:
    group_body = {"id": "group-123", "name": "kb-shared"}
    members_body = {"items": [{"user_id": "outsider"}, {"user_id": "demo"}]}

    assert group_id_from_body(group_body) == "group-123"
    assert group_member_ids_from_body(members_body) == ["outsider", "demo"]


def test_remote_kb_permission_boundary_document_access_summary_normalizes_acl_body() -> None:
    body = {
        "mode": "partial_members",
        "owner_id": "demo",
        "partial_member_list": ["demo"],
        "partial_group_list": ["11111111-1111-1111-1111-111111111111"],
    }

    summary = document_access_summary(body)

    assert summary["mode"] == "partial_members"
    assert summary["owner_id"] == "demo"
    assert summary["partial_member_list"] == ["demo"]
    assert summary["partial_group_list"] == ["11111111-1111-1111-1111-111111111111"]

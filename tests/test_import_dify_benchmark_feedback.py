from __future__ import annotations

from uuid import UUID

from scripts.import_dify_benchmark_feedback import (
    build_feedback_payload,
    build_import_record,
    classify_audit_row,
    select_balanced_audit_rows,
)

TENANT_ID = UUID("00000000-0000-0000-0000-000000000000")


def audit_row(**overrides):
    row = {
        "answer_clause_coverage": 1.0,
        "answer_preview": "模型回答",
        "answer_subquestion_coverage": 1.0,
        "business_score": 1.0,
        "case_id": "bench-0001-mixed-case",
        "case_type": "mixed",
        "dimension_fields": ["办理地点", "收费情况"],
        "evidence_coverage": 1.0,
        "expected_answer_basis": "标准答案",
        "knowledge_id": "changzhou_test",
        "missing_evidence_clause_ids": [],
        "missing_subquestion_ids": [],
        "query": "这个事项怎么办？",
        "score_reason": "准确：回答覆盖全部必答证据。",
        "source_file": "/path/to/gov-service-knowledge/事项.txt",
        "source_record_title": "测试事项",
        "source_section": "01政务服务事项知识",
        "system": "dify_http_mimirq",
        "top_record_preview": "命中的知识片段",
        "verdict": "准确",
        "wrong_evidence_rate": 0.0,
    }
    row.update(overrides)
    return row


def test_classifies_good_bad_and_missed_context_rows():
    good = classify_audit_row(audit_row())
    assert good.bucket == "good"
    assert good.rating == 5
    assert good.issue == "回答良好"

    bad_answer = classify_audit_row(
        audit_row(
            verdict="部分准确",
            answer_subquestion_coverage=0.0,
            business_score=0.55,
            score_reason="部分准确：漏答了用户要求的材料。",
        )
    )
    assert bad_answer.bucket == "bad_answer"
    assert bad_answer.rating == 2
    assert bad_answer.issue == "回答质量差"

    missed = classify_audit_row(
        audit_row(
            verdict="证据不足",
            evidence_coverage=0.25,
            missing_evidence_clause_ids=["材料-1"],
            score_reason="证据不足：没有拿到正确上下文。",
        )
    )
    assert missed.bucket == "missed_context"
    assert missed.rating == 1
    assert missed.issue == "未命中知识库"


def test_build_feedback_payload_keeps_benchmark_context_for_triage():
    payload = build_feedback_payload(
        audit_row(),
        batch_id="dify-http-full800-20260705",
    )

    assert payload.rating == 5
    assert payload.expected_answer == "标准答案"
    assert "评测样本：准确" in payload.reason
    assert "业务分 1.000" in payload.reason
    assert "benchmark:800" in payload.tags
    assert "system:dify_http_mimirq" in payload.tags
    assert "quality:good" in payload.tags
    assert payload.extra["source"] == "benchmark"
    assert payload.extra["feedback_issue"] == "回答良好"
    assert payload.extra["source_record_title"] == "测试事项"
    assert payload.message_metadata["benchmark_feedback_import_key"].endswith(
        "dify_http_mimirq:bench-0001-mixed-case"
    )
    assert len(payload.citations) == 1
    citation = payload.citations[0]
    assert UUID(citation["document_id"])
    assert UUID(citation["chunk_id"])
    assert citation["document_name"] == "测试事项"
    assert citation["chunk_content"] == "命中的知识片段"
    assert citation["retrieval_mode"] == "benchmark"


def test_balanced_selection_keeps_good_and_problem_examples():
    rows = [
        audit_row(case_id="good-1"),
        audit_row(case_id="good-2"),
        audit_row(case_id="partial-1", verdict="部分准确", business_score=0.74),
        audit_row(
            case_id="bad-1",
            verdict="部分准确",
            answer_subquestion_coverage=0.0,
            business_score=0.50,
        ),
        audit_row(
            case_id="miss-1",
            verdict="证据不足",
            evidence_coverage=0.0,
            missing_evidence_clause_ids=["材料-1"],
        ),
    ]

    selected = select_balanced_audit_rows(rows, per_bucket=1, limit=4, seed=11)

    assert len(selected) == 4
    assert {classify_audit_row(row).bucket for row in selected} == {
        "good",
        "partial",
        "bad_answer",
        "missed_context",
    }


def test_import_record_uses_stable_ids_and_pairwise_conversation():
    record = build_import_record(
        audit_row(),
        tenant_id=TENANT_ID,
        account_id="system:benchmark",
        batch_id="dify-http-full800-20260705",
        imported_by="pytest",
    )

    assert record.conversation_id != record.user_message_id
    assert record.assistant_message_id == record.feedback.message_id
    assert record.feedback.conversation_id == record.conversation_id
    assert record.feedback.account_id == "system:benchmark"
    assert record.user_message_content == "这个事项怎么办？"
    assert record.assistant_message_content == "模型回答"

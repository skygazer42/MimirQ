from scripts.dify_3way_benchmark import _is_timeout_error_text
from scripts.evaluate_mixed_rag_quality import evaluate_item


def test_timeout_detection_includes_gateway_504() -> None:
    assert _is_timeout_error_text("HTTP 504: Gateway Time-out") is True
    assert _is_timeout_error_text("HTTP 400: bad request") is False


def test_answer_subquestion_coverage_is_neutral_when_no_subquestions() -> None:
    result = evaluate_item(
        {
            "id": "case-1",
            "evidence_clauses": [
                {"id": "fee", "required_terms": ["事项名称：企业登记", "收费情况：", "不收费"]}
            ],
        },
        {"system": "test"},
        {
            "answer": "企业登记收费情况：不收费",
            "records": [{"content": "收费情况：不收费", "metadata": {"service_name": "企业登记"}}],
        },
    )

    assert result["answer_subquestion_coverage"] == 1.0
    assert result["evidence_coverage"] == 1.0

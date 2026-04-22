from __future__ import annotations

from app.rag.evaluation.metrics.answer_det import evaluate_answer_deterministic


def test_evaluate_answer_deterministic_reports_em_f1_and_refusal() -> None:
    result = evaluate_answer_deterministic(
        question="485 怎么配置？",
        answer="参考 RS-485 配置流程。",
        gold_answer="参考 RS-485 配置流程。",
        is_unanswerable=False,
    )

    assert result["answer_em"] == 1.0
    assert result["answer_f1"] == 1.0
    assert result["refusal_correct"] is None
    assert result["obvious_hallucination"] is False


def test_evaluate_answer_deterministic_handles_unanswerable_refusal() -> None:
    result = evaluate_answer_deterministic(
        question="X9 新型号怎么接线？",
        answer="当前知识库没有相关资料，无法确认。",
        gold_answer="",
        is_unanswerable=True,
    )

    assert result["refusal_correct"] is True

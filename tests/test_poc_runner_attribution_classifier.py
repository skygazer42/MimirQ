from __future__ import annotations

from app.rag.evaluation.poc_runner.attribution_classifier import (
    build_llm_attribution_classifier,
    classify_feedback_records,
)


def test_classify_feedback_records_only_processes_negative_feedback_and_builds_manual_review_queue() -> None:
    records = [
        {
            "interaction_id": "req-1",
            "feedback_score": 1,
            "feedback_polarity": "negative",
            "final_context_filenames": [],
            "feedback_comment": "没检索到",
            "created_at": "2026-04-21T10:00:00Z",
        },
        {
            "interaction_id": "req-2",
            "feedback_score": 5,
            "feedback_polarity": "positive",
            "final_context_filenames": ["manual-a.pdf"],
            "feedback_comment": "很好",
            "created_at": "2026-04-21T10:00:00Z",
        },
    ]

    summary = classify_feedback_records(records, review_confidence_threshold=0.7)

    assert summary["negative_feedback_count"] == 1
    assert summary["counts"]["retrieval_miss"] == 1
    assert summary["counts"]["generation_error"] == 0
    assert summary["counts"]["out_of_scope"] == 0
    assert summary["manual_review_candidates"] == [
        {
            "interaction_id": "req-1",
            "category": "retrieval_miss",
            "confidence": 0.66,
            "rationale": "missing_retrieval_evidence",
        }
    ]


def test_classify_feedback_records_orders_top_examples_by_confidence_then_recentness() -> None:
    rows = [
        {
            "interaction_id": "old-high",
            "feedback_polarity": "negative",
            "feedback_score": 1,
            "created_at": "2026-04-20T10:00:00Z",
        },
        {
            "interaction_id": "new-high",
            "feedback_polarity": "negative",
            "feedback_score": 1,
            "created_at": "2026-04-21T10:00:00Z",
        },
    ]

    labels = {
        "old-high": {"category": "generation_error", "confidence": 0.92, "rationale": "older"},
        "new-high": {"category": "generation_error", "confidence": 0.92, "rationale": "newer"},
    }

    def _classifier(row: dict[str, object]) -> dict[str, object]:
        return labels[str(row["interaction_id"])]

    summary = classify_feedback_records(rows, classifier=_classifier, max_examples_per_category=5)

    assert [item["interaction_id"] for item in summary["top_examples"]["generation_error"]] == [
        "new-high",
        "old-high",
    ]


def test_build_llm_attribution_classifier_uses_llm_output_when_valid() -> None:
    captured: dict[str, str] = {}

    def _fake_llm(prompt: str) -> dict[str, object]:
        captured["prompt"] = prompt
        return {
            "category": "out_of_scope",
            "confidence": 0.91,
            "rationale": "kb truly lacks material",
        }

    classifier = build_llm_attribution_classifier(_fake_llm)
    result = classifier(
        {
            "interaction_id": "req-1",
            "original_query": "新型号 X200 的接线方式",
            "llm_response": "请查看知识库。",
            "feedback_comment": "知识库里没有这个型号",
            "final_context_filenames": ["manual-a.pdf"],
        }
    )

    assert result["category"] == "out_of_scope"
    assert result["confidence"] == 0.91
    assert result["rationale"] == "kb truly lacks material"
    assert "新型号 X200 的接线方式" in captured["prompt"]
    assert "知识库里没有这个型号" in captured["prompt"]
    assert "manual-a.pdf" in captured["prompt"]


def test_build_llm_attribution_classifier_falls_back_to_heuristic_when_llm_output_is_invalid() -> None:
    def _bad_llm(_prompt: str) -> dict[str, object]:
        return {"category": "nonsense", "confidence": 0.2, "rationale": "bad"}

    classifier = build_llm_attribution_classifier(_bad_llm)
    result = classifier(
        {
            "interaction_id": "req-1",
            "feedback_polarity": "negative",
            "feedback_comment": "没检索到",
            "final_context_filenames": [],
        }
    )

    assert result["category"] == "retrieval_miss"
    assert result["rationale"] == "missing_retrieval_evidence"

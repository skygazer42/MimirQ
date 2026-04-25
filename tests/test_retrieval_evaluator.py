from __future__ import annotations


def test_evaluate_retrieval_verdict_distinguishes_correct_ambiguous_incorrect() -> None:
    from app.rag.evaluation.retrieval_evaluator import evaluate_retrieval_verdict

    correct = evaluate_retrieval_verdict(
        retrieval_result={"citations": [{"chunk_id": "c1"}], "metrics": {"top_relevance_score": 0.9}},
        min_citations=1,
        min_top_score=0.35,
    )
    ambiguous = evaluate_retrieval_verdict(
        retrieval_result={"citations": [{"chunk_id": "c1"}], "metrics": {"top_relevance_score": 0.2}},
        min_citations=1,
        min_top_score=0.35,
    )
    incorrect = evaluate_retrieval_verdict(
        retrieval_result={"citations": [], "metrics": {"top_relevance_score": 0.0}, "abstain_triggered": True},
        min_citations=1,
        min_top_score=0.35,
    )

    assert correct["verdict"] == "correct"
    assert ambiguous["verdict"] == "ambiguous"
    assert incorrect["verdict"] == "incorrect"
    assert "top_score_below_min" in list(ambiguous.get("reason_codes") or [])


def test_summarize_retrieval_evaluator_decisions_reports_distribution() -> None:
    from app.rag.evaluation.retrieval_evaluator import summarize_retrieval_evaluator_decisions

    out = summarize_retrieval_evaluator_decisions(
        [
            {"verdict": "correct"},
            {"verdict": "ambiguous"},
            {"verdict": "incorrect"},
            {"verdict": "correct"},
        ]
    )

    assert out["schema"] == "mimirq.retrieval_evaluator_summary.v1"
    assert out["summary"]["evaluated"] == 4
    assert out["summary"]["correct"] == 2
    assert out["summary"]["ambiguous"] == 1
    assert out["summary"]["incorrect"] == 1
    assert out["summary"]["correct_rate"] == 0.5
    assert out["summary"]["ambiguous_rate"] == 0.25
    assert out["summary"]["incorrect_rate"] == 0.25

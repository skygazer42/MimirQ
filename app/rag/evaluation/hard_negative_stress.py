from __future__ import annotations

from typing import Any

from app.rag.evaluation.metrics.answer_det import evaluate_answer_deterministic

HARD_NEGATIVE_CASE_SCHEMA_V1 = "mimirq.hard_negative_case.v1"
HARD_NEGATIVE_STRESS_SUMMARY_SCHEMA_V1 = "mimirq.hard_negative_stress_summary.v1"


def _average(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / float(len(values)), 4)


def evaluate_hard_negative_case(case: dict[str, Any]) -> dict[str, Any]:
    payload = dict(case or {})
    answer_metrics = evaluate_answer_deterministic(
        question=str(payload.get("query") or ""),
        answer=str(payload.get("answer") or ""),
        gold_answer=str(payload.get("gold_answer") or ""),
        is_unanswerable=bool(payload.get("is_unanswerable")),
    )

    citations = list(payload.get("citations") or [])
    answer_em = float(answer_metrics.get("answer_em") or 0.0)
    answer_f1 = float(answer_metrics.get("answer_f1") or 0.0)
    obvious_hallucination = bool(answer_metrics.get("obvious_hallucination"))
    refusal_correct = answer_metrics.get("refusal_correct")

    hard_negative_triggered = bool(
        citations
        and answer_em < 1.0
        and answer_f1 > 0.0
        and not obvious_hallucination
        and refusal_correct is not True
    )
    reason_codes = ["hard_negative_triggered"] if hard_negative_triggered else []

    return {
        "schema": HARD_NEGATIVE_CASE_SCHEMA_V1,
        "case_id": str(payload.get("case_id") or ""),
        "query": str(payload.get("query") or ""),
        "answer_em": answer_em,
        "answer_f1": answer_f1,
        "obvious_hallucination": obvious_hallucination,
        "hard_negative_triggered": hard_negative_triggered,
        "passed": not hard_negative_triggered,
        "reason_codes": reason_codes,
    }


def run_hard_negative_stress(cases: list[dict[str, Any]]) -> dict[str, Any]:
    results = [evaluate_hard_negative_case(case) for case in cases or []]
    total_cases = len(results)
    failed_cases = sum(1 for result in results if not bool(result.get("passed")))
    pass_rate = round((total_cases - failed_cases) / float(total_cases), 4) if total_cases else None
    avg_answer_f1 = _average([float(result.get("answer_f1") or 0.0) for result in results])

    return {
        "schema": HARD_NEGATIVE_STRESS_SUMMARY_SCHEMA_V1,
        "total_cases": int(total_cases),
        "failed_cases": int(failed_cases),
        "pass_rate": pass_rate,
        "avg_answer_f1": avg_answer_f1,
        "results": results,
    }


__all__ = [
    "HARD_NEGATIVE_CASE_SCHEMA_V1",
    "HARD_NEGATIVE_STRESS_SUMMARY_SCHEMA_V1",
    "evaluate_hard_negative_case",
    "run_hard_negative_stress",
]

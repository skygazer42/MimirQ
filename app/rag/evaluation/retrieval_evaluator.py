from typing import Any


def _to_float(value: Any) -> float | None:
    try:
        if value is None or isinstance(value, bool):
            return None
        return float(value)
    except Exception:
        return None


def evaluate_retrieval_verdict(
    *,
    retrieval_result: dict[str, Any],
    min_citations: int,
    min_top_score: float,
) -> dict[str, Any]:
    citations = retrieval_result.get("citations") or []
    metrics = retrieval_result.get("metrics") if isinstance(retrieval_result.get("metrics"), dict) else {}
    citations_total = len(citations) if isinstance(citations, list) else 0
    top_score = _to_float(metrics.get("top_relevance_score"))
    abstain_triggered = bool(retrieval_result.get("abstain_triggered") or metrics.get("abstain_triggered") or False)

    reason_codes: list[str] = []
    verdict = "incorrect"
    if abstain_triggered:
        reason_codes.append("abstain_triggered")
    elif citations_total >= max(1, int(min_citations or 1)) and (top_score or 0.0) >= float(min_top_score or 0.0):
        verdict = "correct"
        reason_codes.append("citations_and_score_sufficient")
    elif citations_total > 0 or (top_score or 0.0) > 0.0:
        verdict = "ambiguous"
        if citations_total < max(1, int(min_citations or 1)):
            reason_codes.append("citations_below_min")
        if (top_score or 0.0) < float(min_top_score or 0.0):
            reason_codes.append("top_score_below_min")
    else:
        reason_codes.append("no_evidence")

    return {
        "schema": "mimirq.retrieval_evaluator.v1",
        "verdict": verdict,
        "citations_total": citations_total,
        "top_relevance_score": top_score or 0.0,
        "abstain_triggered": abstain_triggered,
        "reason_codes": reason_codes,
    }


def summarize_retrieval_evaluator_decisions(rows: list[dict[str, Any]]) -> dict[str, Any]:
    counts = {"correct": 0, "ambiguous": 0, "incorrect": 0}
    for row in rows or []:
        verdict = (row or {}).get("verdict")
        if not isinstance(verdict, str):
            continue
        verdict = verdict.strip().lower()
        if verdict not in counts:
            continue
        counts[verdict] += 1

    total = sum(counts.values())
    return {
        "schema": "mimirq.retrieval_evaluator_summary.v1",
        "summary": {
            "evaluated": total,
            "correct": counts["correct"],
            "ambiguous": counts["ambiguous"],
            "incorrect": counts["incorrect"],
            "correct_rate": round(counts["correct"] / total, 4) if total else 0.0,
            "ambiguous_rate": round(counts["ambiguous"] / total, 4) if total else 0.0,
            "incorrect_rate": round(counts["incorrect"] / total, 4) if total else 0.0,
        },
    }


__all__ = ["evaluate_retrieval_verdict", "summarize_retrieval_evaluator_decisions"]

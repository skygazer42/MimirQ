from __future__ import annotations

from typing import Any, Mapping


def compute_feedback_metrics(
    *,
    all_interactions: int,
    feedback_interactions: int,
    counts: Mapping[str, Any],
) -> dict[str, float]:
    retrieval_miss = int(counts.get("retrieval_miss") or 0)
    generation_error = int(counts.get("generation_error") or 0)
    out_of_scope = int(counts.get("out_of_scope") or 0)
    negative_feedback = retrieval_miss + generation_error + out_of_scope
    positive_feedback = max(0, int(feedback_interactions or 0) - negative_feedback)

    feedback_base = float(feedback_interactions or 0)
    interaction_base = float(all_interactions or 0)

    def _rate(numerator: float, denominator: float) -> float:
        if denominator <= 0:
            return 0.0
        return round(float(numerator) / float(denominator), 4)

    return {
        "raw_positive_rate": _rate(positive_feedback, feedback_base),
        "controllable_positive_rate": _rate(positive_feedback + out_of_scope, feedback_base),
        "knowledge_base_coverage": _rate(feedback_interactions - out_of_scope, feedback_base),
        "retrieval_accuracy": _rate(feedback_interactions - retrieval_miss, feedback_base),
        "generation_accuracy": _rate(feedback_interactions - generation_error, feedback_base),
        "feedback_coverage_rate": _rate(feedback_interactions, interaction_base),
    }

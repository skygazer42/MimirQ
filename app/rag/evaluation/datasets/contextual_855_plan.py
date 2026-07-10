
from typing import Any

CONTEXTUAL_855_EVALSET_PLAN_SCHEMA = "mimirq.contextual_855_evalset_plan.v1"


def build_contextual_855_evalset_plan(
    *,
    target_documents: int = 50,
    target_questions: int = 855,
    avg_relevant_spans_per_question: float = 11.3,
) -> dict[str, Any]:
    return {
        "schema": CONTEXTUAL_855_EVALSET_PLAN_SCHEMA,
        "target_documents": max(1, int(target_documents or 0)),
        "target_questions": max(1, int(target_questions or 0)),
        "avg_relevant_spans_per_question": round(float(avg_relevant_spans_per_question or 0.0), 1),
        "modes": ["basic", "contextual", "expanded"],
        "tracks": [
            "semantic_missing",
            "semantic_ambiguity",
            "structure_loss",
        ],
        "labeling": {
            "granularity": "span_level",
            "question_type_mix": ["factoid", "multi_span", "cross_chunk", "long_context"],
        },
    }


__all__ = ["CONTEXTUAL_855_EVALSET_PLAN_SCHEMA", "build_contextual_855_evalset_plan"]

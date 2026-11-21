from typing import Any, TypedDict

from app.rag.policy.complexity_classifier import classify_query_complexity
from app.rag.retrieval.configuration.profiles import LONG_CONTEXT_RETRIEVAL_PROFILE, PRODUCTION_RETRIEVAL_PROFILE
from app.rag.workflows.base import BaseWorkflow, WorkflowMode, WorkflowResult

_SCHEMA = "mimirq.self_route.v1"


class SelfRouteResult(TypedDict):
    schema: str
    route: str
    retrieval_profile: str
    reason_codes: list[str]


def route_self_query(
    *,
    question: str,
    decision_text: str | None = None,
) -> SelfRouteResult:
    raw_question = question.strip()
    raw_decision = decision_text.strip().lower() if decision_text is not None else None

    route = "rag"

    if raw_decision and ("long_context" in raw_decision or "long context" in raw_decision):
        route = "long_context"
        reason_code = "llm_decision_long_context"
    elif raw_decision and "rag" in raw_decision:
        reason_code = "llm_decision_rag"
    else:
        classified = classify_query_complexity(raw_question)
        question_lower = raw_question.lower()
        if classified["label"] == "multi_hop":
            reason_code = "complexity_multi_hop"
        elif "summarize" in question_lower or "full document" in question_lower:
            route = "long_context"
            reason_code = "heuristic_long_context"
        else:
            reason_code = "heuristic_default_rag"

    retrieval_profile = LONG_CONTEXT_RETRIEVAL_PROFILE if route == "long_context" else PRODUCTION_RETRIEVAL_PROFILE
    return {
        "schema": _SCHEMA,
        "route": route,
        "retrieval_profile": retrieval_profile,
        "reason_codes": [reason_code],
    }


class SelfRouteWorkflow(BaseWorkflow):
    @property
    def mode(self) -> WorkflowMode:
        return WorkflowMode.ROUTING

    async def run(self, state: dict[str, Any]) -> WorkflowResult:
        question = state.get("question")
        if question is None:
            question = state.get("query")
        if question is not None:
            question = question.strip()
        if not question:
            return self.create_result(state, success=False, error="self_route_question_missing")

        route_decision = route_self_query(
            question=question,
            decision_text=state.get("route_decision_text"),
        )
        next_state = dict(state)
        next_state["route_decision"] = route_decision
        next_state["retrieval_profile"] = route_decision["retrieval_profile"]
        return self.create_result(
            next_state,
            success=True,
            metadata={
                "route": route_decision["route"],
                "retrieval_profile": route_decision["retrieval_profile"],
            },
        )


__all__ = ["SelfRouteWorkflow", "route_self_query"]

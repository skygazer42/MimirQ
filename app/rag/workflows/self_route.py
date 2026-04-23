from __future__ import annotations

from typing import Any

from app.rag.core.retrieval_profiles import LONG_CONTEXT_RETRIEVAL_PROFILE, PRODUCTION_RETRIEVAL_PROFILE
from app.rag.policy.complexity_classifier import classify_query_complexity
from app.rag.workflows.base import BaseWorkflow, WorkflowMode, WorkflowResult

_SCHEMA = "mimirq.self_route.v1"


def route_self_query(
    *,
    question: str,
    decision_text: str | None = None,
) -> dict[str, Any]:
    raw_question = str(question or "").strip()
    raw_decision = str(decision_text or "").strip().lower()

    reason_codes: list[str] = []
    route = "rag"
    retrieval_profile = PRODUCTION_RETRIEVAL_PROFILE

    if raw_decision:
        if "long_context" in raw_decision or "long context" in raw_decision:
            route = "long_context"
            retrieval_profile = LONG_CONTEXT_RETRIEVAL_PROFILE
            reason_codes.append("llm_decision_long_context")
        elif "rag" in raw_decision:
            route = "rag"
            retrieval_profile = PRODUCTION_RETRIEVAL_PROFILE
            reason_codes.append("llm_decision_rag")

    if not reason_codes:
        classified = classify_query_complexity(raw_question)
        label = str(classified.get("label") or "")
        if label == "multi_hop":
            route = "rag"
            retrieval_profile = PRODUCTION_RETRIEVAL_PROFILE
            reason_codes.append("complexity_multi_hop")
        elif "summarize" in raw_question.lower() or "full document" in raw_question.lower():
            route = "long_context"
            retrieval_profile = LONG_CONTEXT_RETRIEVAL_PROFILE
            reason_codes.append("heuristic_long_context")
        else:
            route = "rag"
            retrieval_profile = PRODUCTION_RETRIEVAL_PROFILE
            reason_codes.append("heuristic_default_rag")

    return {
        "schema": _SCHEMA,
        "route": route,
        "retrieval_profile": retrieval_profile,
        "reason_codes": reason_codes,
    }


class SelfRouteWorkflow(BaseWorkflow):
    @property
    def mode(self) -> WorkflowMode:
        return WorkflowMode.ROUTING

    async def run(self, state: dict[str, Any]) -> WorkflowResult:
        question = str(state.get("question") or state.get("query") or "").strip()
        if not question:
            return self.create_result(state, success=False, error="self_route_question_missing")

        route_decision = route_self_query(
            question=question,
            decision_text=state.get("route_decision_text"),
        )
        next_state = dict(state)
        next_state["route_decision"] = route_decision
        next_state["retrieval_profile"] = route_decision.get("retrieval_profile")
        return self.create_result(
            next_state,
            success=True,
            metadata={
                "route": route_decision.get("route"),
                "retrieval_profile": route_decision.get("retrieval_profile"),
            },
        )


__all__ = ["SelfRouteWorkflow", "route_self_query"]

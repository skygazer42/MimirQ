from collections.abc import Callable
from typing import Any, TypedDict

from app.rag.core.query_rewrite_strategy import (
    DEFAULT_QUERY_REWRITE_STRATEGY_ID,
    build_query_rewrite_strategy_spec,
    resolve_query_rewrite_strategy_id,
)
from app.rag.workflows.base import BaseWorkflow, WorkflowMode, WorkflowResult

_SCHEMA = "mimirq.query_rewrite_workflow.v1"


class QueryRewriteResult(TypedDict):
    schema: str
    original: str
    rewritten: str
    used: bool
    strategy_id: str
    strategy_hash: str


def run_query_rewrite_workflow(
    *,
    question: str,
    history_text: str,
    strategy_id: str | None = None,
    rewriter: Callable[[str, str, str], str] | None = None,
) -> QueryRewriteResult:
    original = question.strip()
    history = history_text.strip()
    resolved_strategy = resolve_query_rewrite_strategy_id(strategy_id or DEFAULT_QUERY_REWRITE_STRATEGY_ID)
    spec = build_query_rewrite_strategy_spec(resolved_strategy)

    rewritten = original
    if rewriter is not None:
        try:
            candidate = rewriter(original, history, resolved_strategy)
            if candidate is not None:
                candidate = candidate.strip()
        except Exception:
            candidate = None
        if candidate:
            rewritten = candidate

    used = bool(rewritten and rewritten != original)
    return {
        "schema": _SCHEMA,
        "original": original,
        "rewritten": rewritten or original,
        "used": used,
        "strategy_id": spec["strategy_id"],
        "strategy_hash": spec["strategy_hash"],
    }


class QueryRewriteWorkflow(BaseWorkflow):
    @property
    def mode(self) -> WorkflowMode:
        return WorkflowMode.CHAIN

    async def run(self, state: dict[str, Any]) -> WorkflowResult:
        question = state.get("question")
        if question is None:
            question = state.get("query")
        if question is not None:
            question = question.strip()
        if not question:
            return self.create_result(state, success=False, error="query_rewrite_question_missing")

        history_text = state.get("history_text")
        if history_text is not None:
            history_text = history_text.strip()
        rewriter = state.get("query_rewriter")
        rewrite = run_query_rewrite_workflow(
            question=question,
            history_text=history_text if history_text is not None else "",
            strategy_id=state.get("query_rewrite_strategy"),
            rewriter=rewriter if callable(rewriter) else None,
        )
        next_state = dict(state)
        next_state["rewrite"] = rewrite
        next_state["query_for_retrieval"] = rewrite["rewritten"] or question
        return self.create_result(
            next_state,
            success=True,
            metadata={
                "used": rewrite["used"],
                "strategy_id": rewrite["strategy_id"],
            },
        )


__all__ = ["QueryRewriteWorkflow", "run_query_rewrite_workflow"]

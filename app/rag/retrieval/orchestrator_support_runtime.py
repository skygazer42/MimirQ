from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from app.rag.retrieval.orchestration.query_contracts import QueryPlan


@dataclass
class RetrievalRuntimeState:
    """Shared state passed through the ordered retrieval phases."""

    state: dict[str, Any]
    question: str
    history_text: str
    _query_plan: QueryPlan | None = field(default=None, init=False, repr=False)

    @property
    def query_plan(self) -> QueryPlan:
        if self._query_plan is None:
            raise RuntimeError("Retrieval query plan has not been prepared")
        return self._query_plan

    @query_plan.setter
    def query_plan(self, plan: QueryPlan) -> None:
        self._query_plan = plan

    @property
    def query_for_retrieval(self) -> str:
        return self.query_plan.query

    @property
    def rewrite_used(self) -> bool:
        return self.query_plan.prepared.rewrite.used

    @property
    def alias_queries(self) -> list[str]:
        return self.query_plan.deterministic.alias.queries

    @property
    def multi_queries(self) -> list[str]:
        return self.query_plan.models.multi_query.queries

    @property
    def retrieval_contract_policy(self) -> dict[str, Any]:
        return self.query_plan.routing.normalization.retrieval_contract_policy

    @property
    def hierarchy_recall_enabled(self) -> bool:
        return self.query_plan.routing.normalization.hierarchy.enabled


RetrievalPhase = Callable[[RetrievalRuntimeState], dict[str, Any] | None]


def run_retrieval_runtime(
    runtime: RetrievalRuntimeState,
    *,
    phases: Sequence[RetrievalPhase],
) -> dict[str, Any]:
    """Run retrieval phases in order and return the terminal phase result."""
    for phase in phases:
        result = phase(runtime)
        if result is not None:
            return result
    raise RuntimeError("retrieval runtime completed without a result")

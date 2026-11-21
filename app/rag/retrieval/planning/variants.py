from dataclasses import dataclass
from typing import Any

from app.infrastructure.tokens import num_tokens_from_string
from app.rag.retrieval.planning.contracts import QueryExpansionBudget


@dataclass(frozen=True)
class QueryVariantStageInput:
    query_for_retrieval: str
    alias_queries: list[str]
    dict_expansions: list[dict[str, Any]]
    kg_query_expansion_queries: list[str]
    clause_fastlane_queries: list[str]
    lightweight_subqueries: list[str]
    multi_queries: list[str]
    step_back_used: bool
    step_back_query: str
    sub_questions: list[str]
    hyde_used: bool
    hyde_text: str
    budget: QueryExpansionBudget
    query_expansion_elapsed_ms: float
    multi_query_last: bool = False


@dataclass(frozen=True)
class QueryVariantStageOutput:
    retrieval_queries: list[tuple[str, str]]
    query_expansion_budget_meta: dict[str, Any]
    query_expansion_budget_max_queries: int
    query_expansion_budget_max_candidates: int
    query_expansion_budget_token_budget: int
    query_expansion_budget_latency_ms: float


def _build_retrieval_queries(payload: QueryVariantStageInput) -> list[tuple[str, str]]:
    retrieval_queries: list[tuple[str, str]] = [("main", payload.query_for_retrieval)]
    retrieval_queries.extend(("alias", query) for query in payload.alias_queries)
    for expansion in payload.dict_expansions:
        expanded_text = expansion["expanded_text"]
        if expanded_text:
            retrieval_queries.append(("dict", expanded_text))
    retrieval_queries.extend(("kgq", query) for query in payload.kg_query_expansion_queries)
    retrieval_queries.extend(("clause", query) for query in payload.clause_fastlane_queries)
    retrieval_queries.extend(("lite_subq", query) for query in payload.lightweight_subqueries)
    if not payload.multi_query_last:
        retrieval_queries.extend(("mq", query) for query in payload.multi_queries)
    if payload.step_back_used and payload.step_back_query:
        retrieval_queries.append(("step_back", payload.step_back_query))
    retrieval_queries.extend(("subq", query) for query in payload.sub_questions)
    if payload.hyde_used and payload.hyde_text:
        retrieval_queries.append(("hyde", payload.hyde_text))
    if payload.multi_query_last:
        retrieval_queries.extend(("mq", query) for query in payload.multi_queries)
    return deduplicate_retrieval_queries(retrieval_queries)


def _budget_meta(
    *,
    retrieval_queries: list[tuple[str, str]],
    budget: QueryExpansionBudget,
    elapsed_ms: float,
) -> dict[str, Any]:
    return {
        "enabled": bool(budget.max_queries or budget.max_candidates or budget.token_budget or budget.latency_budget_ms),
        "max_queries": budget.max_queries,
        "max_candidates": budget.max_candidates,
        "token_budget": budget.token_budget,
        "latency_budget_ms": round(float(budget.latency_budget_ms), 3),
        "generation_elapsed_ms": round(float(elapsed_ms), 3),
        "candidate_count": max(0, len(retrieval_queries) - 1),
        "selected_count": 0,
        "selected_tokens": 0,
        "dropped_count": 0,
        "degraded": False,
        "reasons": [],
    }


def _filter_budgeted_queries(
    *,
    retrieval_queries: list[tuple[str, str]],
    budget_meta: dict[str, Any],
    budget: QueryExpansionBudget,
    elapsed_ms: float,
) -> tuple[list[tuple[str, str]], int]:
    main_query = retrieval_queries[0]
    extra_queries = retrieval_queries[1:]
    filtered_extra_queries: list[tuple[str, str]] = []
    selected_tokens = 0
    latency_budget_exceeded = budget.latency_budget_ms > 0.0 and elapsed_ms > budget.latency_budget_ms
    if latency_budget_exceeded:
        budget_meta["reasons"].append("latency_budget_exceeded")
    for kind, query in extra_queries:
        if budget.max_candidates > 0 and len(filtered_extra_queries) >= budget.max_candidates:
            budget_meta["reasons"].append("candidate_budget_exceeded")
            continue
        if budget.max_queries > 0 and len(filtered_extra_queries) >= budget.max_queries:
            budget_meta["reasons"].append("query_budget_exceeded")
            continue
        query_tokens = num_tokens_from_string(query)
        if budget.token_budget > 0 and selected_tokens + query_tokens > budget.token_budget:
            budget_meta["reasons"].append("token_budget_exceeded")
            continue
        if latency_budget_exceeded and kind in {"mq", "step_back", "subq", "hyde"}:
            budget_meta["reasons"].append(f"latency_budget_drop:{kind}")
            continue
        filtered_extra_queries.append((kind, query))
        selected_tokens += query_tokens
    return [main_query] + filtered_extra_queries, selected_tokens


def build_query_variant_stage(payload: QueryVariantStageInput) -> QueryVariantStageOutput:
    retrieval_queries = _build_retrieval_queries(payload)

    budget = payload.budget
    query_expansion_budget_meta = _budget_meta(
        retrieval_queries=retrieval_queries,
        budget=budget,
        elapsed_ms=payload.query_expansion_elapsed_ms,
    )
    if query_expansion_budget_meta["enabled"] and retrieval_queries:
        retrieval_queries, selected_tokens = _filter_budgeted_queries(
            retrieval_queries=retrieval_queries,
            budget_meta=query_expansion_budget_meta,
            budget=budget,
            elapsed_ms=payload.query_expansion_elapsed_ms,
        )
        selected_count = len(retrieval_queries) - 1
        query_expansion_budget_meta["selected_count"] = selected_count
        query_expansion_budget_meta["selected_tokens"] = selected_tokens
        query_expansion_budget_meta["dropped_count"] = query_expansion_budget_meta["candidate_count"] - selected_count
        query_expansion_budget_meta["reasons"] = list(dict.fromkeys(query_expansion_budget_meta["reasons"]))
        query_expansion_budget_meta["degraded"] = query_expansion_budget_meta["dropped_count"] > 0

    return QueryVariantStageOutput(
        retrieval_queries=retrieval_queries,
        query_expansion_budget_meta=query_expansion_budget_meta,
        query_expansion_budget_max_queries=budget.max_queries,
        query_expansion_budget_max_candidates=budget.max_candidates,
        query_expansion_budget_token_budget=budget.token_budget,
        query_expansion_budget_latency_ms=budget.latency_budget_ms,
    )


def normalize_retrieval_query(text: str) -> str:
    return " ".join(text.split())


def deduplicate_retrieval_queries(queries: list[tuple[str, str]]) -> list[tuple[str, str]]:
    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    for kind, q in queries:
        norm = normalize_retrieval_query(q)
        if not norm:
            continue
        key = norm.casefold() if norm.isascii() else norm
        if key in seen:
            continue
        seen.add(key)
        out.append((kind, norm))
    return out

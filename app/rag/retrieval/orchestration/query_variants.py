
from dataclasses import dataclass
from typing import Any

from app.core.token_utils import num_tokens_from_string


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
    query_expansion_max_queries_raw: Any
    query_expansion_max_candidates_raw: Any
    query_expansion_token_budget_raw: Any
    query_expansion_latency_budget_ms_raw: Any
    query_expansion_elapsed_ms: float


@dataclass(frozen=True)
class QueryVariantStageOutput:
    retrieval_queries: list[tuple[str, str]]
    query_expansion_budget_meta: dict[str, Any]
    query_expansion_budget_max_queries: int
    query_expansion_budget_max_candidates: int
    query_expansion_budget_token_budget: int
    query_expansion_budget_latency_ms: float


def _coerce_budget_int(raw: Any) -> int:
    try:
        return max(0, int(raw or 0))
    except (TypeError, ValueError, AttributeError):
        return 0


def _coerce_budget_float(raw: Any) -> float:
    try:
        return max(0.0, float(raw or 0.0))
    except (TypeError, ValueError, AttributeError):
        return 0.0


def _dedupe_query_variants(retrieval_queries: list[tuple[str, str]]) -> list[tuple[str, str]]:
    seen_queries: set[str] = set()
    deduped_queries: list[tuple[str, str]] = []
    for kind, query in retrieval_queries:
        normalized = " ".join((query or "").strip().split())
        if not normalized:
            continue
        key = normalized.casefold() if normalized.isascii() else normalized
        if key in seen_queries:
            continue
        seen_queries.add(key)
        deduped_queries.append((kind, normalized))
    return deduped_queries


def build_query_variant_stage(payload: QueryVariantStageInput) -> QueryVariantStageOutput:
    retrieval_queries: list[tuple[str, str]] = [("main", payload.query_for_retrieval)]
    for query in payload.alias_queries:
        retrieval_queries.append(("alias", query))
    for expansion in payload.dict_expansions:
        expanded_text = expansion.get("expanded_text") if isinstance(expansion, dict) else None
        if expanded_text:
            retrieval_queries.append(("dict", str(expanded_text)))
    for query in payload.kg_query_expansion_queries:
        retrieval_queries.append(("kgq", query))
    for query in payload.clause_fastlane_queries:
        retrieval_queries.append(("clause", query))
    for query in payload.lightweight_subqueries:
        retrieval_queries.append(("lite_subq", query))
    for query in payload.multi_queries:
        retrieval_queries.append(("mq", query))
    if payload.step_back_used and payload.step_back_query:
        retrieval_queries.append(("step_back", payload.step_back_query))
    for query in payload.sub_questions:
        retrieval_queries.append(("subq", query))
    if payload.hyde_used and payload.hyde_text:
        retrieval_queries.append(("hyde", payload.hyde_text))

    retrieval_queries = _dedupe_query_variants(retrieval_queries)

    query_expansion_budget_max_queries = _coerce_budget_int(payload.query_expansion_max_queries_raw)
    query_expansion_budget_max_candidates = _coerce_budget_int(payload.query_expansion_max_candidates_raw)
    query_expansion_budget_token_budget = _coerce_budget_int(payload.query_expansion_token_budget_raw)
    query_expansion_budget_latency_ms = _coerce_budget_float(payload.query_expansion_latency_budget_ms_raw)
    query_expansion_budget_meta: dict[str, Any] = {
        "enabled": bool(
            query_expansion_budget_max_queries
            or query_expansion_budget_max_candidates
            or query_expansion_budget_token_budget
            or query_expansion_budget_latency_ms
        ),
        "max_queries": int(query_expansion_budget_max_queries or 0),
        "max_candidates": int(query_expansion_budget_max_candidates or 0),
        "token_budget": int(query_expansion_budget_token_budget or 0),
        "latency_budget_ms": round(float(query_expansion_budget_latency_ms or 0.0), 3),
        "generation_elapsed_ms": round(float(payload.query_expansion_elapsed_ms or 0.0), 3),
        "candidate_count": int(max(0, len(retrieval_queries) - 1)),
        "selected_count": 0,
        "selected_tokens": 0,
        "dropped_count": 0,
        "degraded": False,
        "reasons": [],
    }
    if query_expansion_budget_meta["enabled"] and retrieval_queries:
        main_query = retrieval_queries[0]
        extra_queries = retrieval_queries[1:]
        filtered_extra_queries: list[tuple[str, str]] = []
        selected_tokens = 0
        latency_budget_exceeded = bool(
            query_expansion_budget_latency_ms > 0.0
            and payload.query_expansion_elapsed_ms > query_expansion_budget_latency_ms
        )
        if latency_budget_exceeded:
            query_expansion_budget_meta["reasons"].append("latency_budget_exceeded")
        for kind, query in extra_queries:
            query_tokens = num_tokens_from_string(query or "")
            if query_expansion_budget_max_candidates > 0 and len(filtered_extra_queries) >= query_expansion_budget_max_candidates:
                query_expansion_budget_meta["reasons"].append("candidate_budget_exceeded")
                continue
            if query_expansion_budget_max_queries > 0 and len(filtered_extra_queries) >= query_expansion_budget_max_queries:
                query_expansion_budget_meta["reasons"].append("query_budget_exceeded")
                continue
            if query_expansion_budget_token_budget > 0 and (selected_tokens + query_tokens) > query_expansion_budget_token_budget:
                query_expansion_budget_meta["reasons"].append("token_budget_exceeded")
                continue
            if latency_budget_exceeded and kind in {"mq", "step_back", "subq", "hyde"}:
                query_expansion_budget_meta["reasons"].append(f"latency_budget_drop:{kind}")
                continue
            filtered_extra_queries.append((kind, query))
            selected_tokens += int(query_tokens)

        retrieval_queries = [main_query] + filtered_extra_queries
        query_expansion_budget_meta["selected_count"] = int(len(filtered_extra_queries))
        query_expansion_budget_meta["selected_tokens"] = int(selected_tokens)
        query_expansion_budget_meta["dropped_count"] = int(max(0, len(extra_queries) - len(filtered_extra_queries)))
        query_expansion_budget_meta["reasons"] = list(dict.fromkeys(query_expansion_budget_meta["reasons"]))
        query_expansion_budget_meta["degraded"] = bool(query_expansion_budget_meta["dropped_count"] > 0)

    return QueryVariantStageOutput(
        retrieval_queries=retrieval_queries,
        query_expansion_budget_meta=query_expansion_budget_meta,
        query_expansion_budget_max_queries=query_expansion_budget_max_queries,
        query_expansion_budget_max_candidates=query_expansion_budget_max_candidates,
        query_expansion_budget_token_budget=query_expansion_budget_token_budget,
        query_expansion_budget_latency_ms=query_expansion_budget_latency_ms,
    )

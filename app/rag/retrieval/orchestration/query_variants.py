
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


def _extend_queries(retrieval_queries: list[tuple[str, str]], kind: str, queries: list[str]) -> None:
    for query in queries:
        retrieval_queries.append((kind, query))


def _build_retrieval_queries(payload: QueryVariantStageInput) -> list[tuple[str, str]]:
    retrieval_queries: list[tuple[str, str]] = [("main", payload.query_for_retrieval)]
    _extend_queries(retrieval_queries, "alias", payload.alias_queries)
    for expansion in payload.dict_expansions:
        expanded_text = expansion.get("expanded_text") if isinstance(expansion, dict) else None
        if expanded_text:
            retrieval_queries.append(("dict", str(expanded_text)))
    _extend_queries(retrieval_queries, "kgq", payload.kg_query_expansion_queries)
    _extend_queries(retrieval_queries, "clause", payload.clause_fastlane_queries)
    _extend_queries(retrieval_queries, "lite_subq", payload.lightweight_subqueries)
    _extend_queries(retrieval_queries, "mq", payload.multi_queries)
    if payload.step_back_used and payload.step_back_query:
        retrieval_queries.append(("step_back", payload.step_back_query))
    _extend_queries(retrieval_queries, "subq", payload.sub_questions)
    if payload.hyde_used and payload.hyde_text:
        retrieval_queries.append(("hyde", payload.hyde_text))
    return _dedupe_query_variants(retrieval_queries)


def _budget_meta(
    *,
    retrieval_queries: list[tuple[str, str]],
    max_queries: int,
    max_candidates: int,
    token_budget: int,
    latency_budget_ms: float,
    elapsed_ms: float,
) -> dict[str, Any]:
    return {
        "enabled": bool(max_queries or max_candidates or token_budget or latency_budget_ms),
        "max_queries": int(max_queries or 0),
        "max_candidates": int(max_candidates or 0),
        "token_budget": int(token_budget or 0),
        "latency_budget_ms": round(float(latency_budget_ms or 0.0), 3),
        "generation_elapsed_ms": round(float(elapsed_ms or 0.0), 3),
        "candidate_count": int(max(0, len(retrieval_queries) - 1)),
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
    max_queries: int,
    max_candidates: int,
    token_budget: int,
    latency_budget_ms: float,
    elapsed_ms: float,
) -> tuple[list[tuple[str, str]], int]:
    if not budget_meta["enabled"] or not retrieval_queries:
        return retrieval_queries, 0
    main_query = retrieval_queries[0]
    extra_queries = retrieval_queries[1:]
    filtered_extra_queries: list[tuple[str, str]] = []
    selected_tokens = 0
    latency_budget_exceeded = bool(latency_budget_ms > 0.0 and elapsed_ms > latency_budget_ms)
    if latency_budget_exceeded:
        budget_meta["reasons"].append("latency_budget_exceeded")
    for kind, query in extra_queries:
        query_tokens = num_tokens_from_string(query or "")
        if max_candidates > 0 and len(filtered_extra_queries) >= max_candidates:
            budget_meta["reasons"].append("candidate_budget_exceeded")
            continue
        if max_queries > 0 and len(filtered_extra_queries) >= max_queries:
            budget_meta["reasons"].append("query_budget_exceeded")
            continue
        if token_budget > 0 and (selected_tokens + query_tokens) > token_budget:
            budget_meta["reasons"].append("token_budget_exceeded")
            continue
        if latency_budget_exceeded and kind in {"mq", "step_back", "subq", "hyde"}:
            budget_meta["reasons"].append(f"latency_budget_drop:{kind}")
            continue
        filtered_extra_queries.append((kind, query))
        selected_tokens += int(query_tokens)
    return [main_query] + filtered_extra_queries, selected_tokens


def build_query_variant_stage(payload: QueryVariantStageInput) -> QueryVariantStageOutput:
    retrieval_queries = _build_retrieval_queries(payload)

    query_expansion_budget_max_queries = _coerce_budget_int(payload.query_expansion_max_queries_raw)
    query_expansion_budget_max_candidates = _coerce_budget_int(payload.query_expansion_max_candidates_raw)
    query_expansion_budget_token_budget = _coerce_budget_int(payload.query_expansion_token_budget_raw)
    query_expansion_budget_latency_ms = _coerce_budget_float(payload.query_expansion_latency_budget_ms_raw)
    query_expansion_budget_meta = _budget_meta(
        retrieval_queries=retrieval_queries,
        max_queries=query_expansion_budget_max_queries,
        max_candidates=query_expansion_budget_max_candidates,
        token_budget=query_expansion_budget_token_budget,
        latency_budget_ms=query_expansion_budget_latency_ms,
        elapsed_ms=payload.query_expansion_elapsed_ms,
    )
    if query_expansion_budget_meta["enabled"] and retrieval_queries:
        extra_queries = retrieval_queries[1:]
        retrieval_queries, selected_tokens = _filter_budgeted_queries(
            retrieval_queries=retrieval_queries,
            budget_meta=query_expansion_budget_meta,
            max_queries=query_expansion_budget_max_queries,
            max_candidates=query_expansion_budget_max_candidates,
            token_budget=query_expansion_budget_token_budget,
            latency_budget_ms=query_expansion_budget_latency_ms,
            elapsed_ms=payload.query_expansion_elapsed_ms,
        )
        query_expansion_budget_meta["selected_count"] = int(max(0, len(retrieval_queries) - 1))
        query_expansion_budget_meta["selected_tokens"] = int(selected_tokens)
        query_expansion_budget_meta["dropped_count"] = int(max(0, len(extra_queries) - query_expansion_budget_meta["selected_count"]))
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

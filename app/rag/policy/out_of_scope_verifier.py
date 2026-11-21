"""Shared keyword/vector/HyDE scope verdicts without evaluation or storage imports."""

import logging
from typing import Any, Callable, Mapping, Sequence


def _safe_str(value: Any, *, max_len: int = 2_000) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text[: max(1, int(max_len or 1))]


def _best_score(rows: Sequence[dict[str, Any]] | None) -> float | None:
    best: float | None = None
    for item in rows if rows is not None else []:
        if not isinstance(item, dict):
            continue
        try:
            score = float(item.get("score"))
        except (OverflowError, TypeError, ValueError):
            logging.getLogger("app.rag.evaluation.poc_runner.out_of_scope_verifier").debug(
                "Skipping item after non-critical exception", exc_info=True
            )
            continue
        if best is None or score > best:
            best = score
    return round(best, 4) if best is not None else None


def _expand_query(query: str, glossary: Mapping[str, Sequence[str]] | None) -> str:
    expanded: list[str] = [query.strip()]
    q_norm = expanded[0]
    for key, values in (glossary if glossary is not None else {}).items():
        term = key.strip()
        if not term or term not in q_norm:
            continue
        for value in values or []:
            alias = value.strip()
            if alias and alias not in expanded:
                expanded.append(alias)
    return " ".join(part for part in expanded if part)


def verify_out_of_scope_query(
    *,
    query: str,
    glossary: Mapping[str, Sequence[str]] | None,
    keyword_search: Callable[[str], Sequence[dict[str, Any]]],
    vector_search: Callable[[str], Sequence[dict[str, Any]]],
    hyde_generate: Callable[[str], str | None],
    vector_similarity_threshold: float,
    hyde_similarity_threshold: float,
    enable_keyword: bool = True,
    enable_vector: bool = True,
    enable_hyde: bool = True,
) -> dict[str, Any]:
    expanded_query = _expand_query(query, glossary)

    keyword_hits = list(keyword_search(expanded_query)) if enable_keyword else []
    l1_keyword_hit = bool(keyword_hits) if enable_keyword else None

    vector_hits = list(vector_search(query)) if enable_vector else []
    l2_top1_sim = _best_score(vector_hits) if enable_vector else None

    l3_hyde_query = _safe_str(hyde_generate(query)) if enable_hyde else None
    hyde_hits = list(vector_search(l3_hyde_query)) if enable_hyde and l3_hyde_query else []
    hyde_top1 = _best_score(hyde_hits) if enable_hyde and l3_hyde_query else None
    l3_hyde_hit = (
        None if not enable_hyde else bool(hyde_top1 is not None and hyde_top1 >= float(hyde_similarity_threshold))
    )

    verdict = "out_of_scope"
    if l1_keyword_hit:
        verdict = "in_scope"
    elif l2_top1_sim is not None and l2_top1_sim >= float(vector_similarity_threshold):
        verdict = "in_scope"
    elif l3_hyde_hit:
        verdict = "in_scope"
    else:
        near_vector = l2_top1_sim is not None and l2_top1_sim >= float(vector_similarity_threshold) * 0.75
        near_hyde = hyde_top1 is not None and hyde_top1 >= float(hyde_similarity_threshold) * 0.75
        if near_vector or near_hyde:
            verdict = "ambiguous"

    return {
        "query": query.strip(),
        "expanded_query": expanded_query,
        "l1_keyword_hit": l1_keyword_hit,
        "l2_top1_sim": l2_top1_sim,
        "l3_hyde_query": l3_hyde_query,
        "l3_hyde_top1_sim": hyde_top1,
        "l3_hyde_hit": l3_hyde_hit,
        "verdict": verdict,
        "enabled_stages": {
            "keyword": bool(enable_keyword),
            "vector": bool(enable_vector),
            "hyde": bool(enable_hyde),
        },
    }


def maybe_apply_out_of_scope_live_guard(
    *,
    query: str,
    enabled: bool,
    candidate: bool,
    current_triggered: bool,
    current_reason: str | None,
    tenant_id: str | None,
    dataset_id: str | None,
    verifier: Callable[[], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    applied = bool(enabled and candidate and query.strip() and tenant_id and dataset_id)
    verdict = dict(verifier()) if applied and verifier is not None else {}
    out_of_scope = bool(verdict) and verdict["verdict"] == "out_of_scope"
    return {
        "applied": applied,
        "abstain_triggered": out_of_scope or bool(current_triggered),
        "abstain_reason": "out_of_scope" if out_of_scope else current_reason,
        "verdict": verdict or None,
    }


__all__ = ["maybe_apply_out_of_scope_live_guard", "verify_out_of_scope_query"]

"""Local out-of-scope guard helpers for retrieval orchestration.

This mirrors the policy-layer guard without importing ``app.rag.evaluation``.
"""

from typing import Any, Callable, Mapping, Sequence
from uuid import UUID

from app.rag.core.logging import get_logger
from app.rag.industry_rules.loaders import load_ruleset
from app.rag.retrieval.orchestration.retriever_shim import get_vector_store, hybrid_retriever

_SCHEMA = "mimirq.out_of_scope_live_guard.v1"


def _safe_str(value: Any, *, max_len: int = 2_000) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    return text[: max(1, int(max_len or 1))]


def _best_score(rows: Sequence[dict[str, Any]] | None) -> float | None:
    best: float | None = None
    for item in rows or []:
        if not isinstance(item, dict):
            continue
        try:
            score = float(item.get("score"))
        except Exception:
            get_logger(__name__).debug("Skipping item after non-critical exception", exc_info=True)
            continue
        if best is None or score > best:
            best = score
    return round(best, 4) if best is not None else None


def _expand_query(query: str, glossary: Mapping[str, Sequence[str]] | None) -> str:
    expanded: list[str] = [str(query or "").strip()]
    q_norm = expanded[0]
    for key, values in (glossary or {}).items():
        term = str(key or "").strip()
        if not term or term not in q_norm:
            continue
        for value in values or []:
            alias = str(value or "").strip()
            if alias and alias not in expanded:
                expanded.append(alias)
    return " ".join(part for part in expanded if part)


def verify_out_of_scope_query(
    *,
    query: str,
    glossary: Mapping[str, Sequence[str]] | None,
    keyword_search: Callable[[str], Sequence[dict[str, Any]]],
    vector_search: Callable[[str], Sequence[dict[str, Any]]],
    hyde_generate: Callable[[str], str],
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
    hyde_hits = list(vector_search(l3_hyde_query or "")) if enable_hyde and l3_hyde_query else []
    hyde_top1 = _best_score(hyde_hits) if enable_hyde and l3_hyde_query else None
    l3_hyde_hit = None if not enable_hyde else bool(hyde_top1 is not None and hyde_top1 >= float(hyde_similarity_threshold))

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
        "query": str(query or "").strip(),
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


def run_default_out_of_scope_live_guard(
    *,
    query: str,
    tenant_id: str,
    dataset_id: str,
    ruleset_name: str | None = None,
    hyde_query: str | None = None,
    vector_similarity_threshold: float = 0.35,
    hyde_similarity_threshold: float = 0.4,
) -> dict[str, Any]:
    tenant_uuid = UUID(str(tenant_id))
    dataset_uuid = UUID(str(dataset_id))
    glossary: Mapping[str, Sequence[str]] = {}
    if str(ruleset_name or "").strip():
        try:
            glossary = load_ruleset(str(ruleset_name)).glossary
        except Exception:
            glossary = {}

    retriever = hybrid_retriever.model_copy(
        update={
            "tenant_id": tenant_uuid,
            "dataset_id": dataset_uuid,
            "score_threshold": 0.0,
            "k": 3,
        }
    )

    def _keyword_search(text: str) -> Sequence[dict[str, Any]]:
        return retriever._search_bm25(  # noqa: SLF001
            query=text,
            top_k=3,
            tenant_id=tenant_uuid,
            metadata_filter={"dataset_id": str(dataset_uuid)},
        )

    def _vector_search(text: str) -> Sequence[dict[str, Any]]:
        if not str(text or "").strip():
            return []
        try:
            rows = get_vector_store().search(
                query=str(text),
                top_k=3,
                score_threshold=0.0,
                tenant_id=tenant_uuid,
                metadata_filter={"dataset_id": str(dataset_uuid)},
            )
        except Exception:
            return []
        return [{"score": float(item.get("score") or 0.0)} for item in rows if isinstance(item, dict)]

    verdict = verify_out_of_scope_query(
        query=str(query or "").strip(),
        glossary=glossary,
        keyword_search=_keyword_search,
        vector_search=_vector_search,
        hyde_generate=lambda _q: str(hyde_query or "").strip(),
        vector_similarity_threshold=float(vector_similarity_threshold),
        hyde_similarity_threshold=float(hyde_similarity_threshold),
        enable_keyword=True,
        enable_vector=True,
        enable_hyde=bool(str(hyde_query or "").strip()),
    )
    return {"schema": _SCHEMA, **dict(verdict or {})}


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
    if not bool(enabled) or not bool(candidate) or not str(query or "").strip() or not tenant_id or not dataset_id:
        return {
            "applied": False,
            "abstain_triggered": bool(current_triggered),
            "abstain_reason": current_reason,
            "verdict": None,
        }

    verdict = dict(verifier() or {}) if verifier is not None else {}
    if not verdict:
        return {
            "applied": True,
            "abstain_triggered": bool(current_triggered),
            "abstain_reason": current_reason,
            "verdict": None,
        }

    if str(verdict.get("verdict") or "") == "out_of_scope":
        return {
            "applied": True,
            "abstain_triggered": True,
            "abstain_reason": "out_of_scope",
            "verdict": verdict,
        }

    return {
        "applied": True,
        "abstain_triggered": bool(current_triggered),
        "abstain_reason": current_reason,
        "verdict": verdict,
    }


__all__ = [
    "maybe_apply_out_of_scope_live_guard",
    "run_default_out_of_scope_live_guard",
    "verify_out_of_scope_query",
]

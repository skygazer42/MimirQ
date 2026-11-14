from typing import Any, Callable, Mapping, Sequence
from uuid import UUID

from app.rag.core.logging import get_logger
from app.rag.evaluation.poc_runner.out_of_scope_verifier import verify_out_of_scope_query
from app.rag.industry_rules.loaders import load_ruleset
from app.rag.retriever import hybrid_retriever
from app.storage.vector.factory import get_vector_store

_SCHEMA = "mimirq.out_of_scope_live_guard.v1"


def _normalize_vector_hits(rows: Sequence[dict[str, Any]] | None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in rows or []:
        if not isinstance(item, dict):
            continue
        meta = item.get("metadata") or {}
        score = item.get("score")
        if score is None:
            score = item.get("relevance_score")
        if score is None and isinstance(meta, dict):
            for key in ("relevance_score", "retrieval_score", "score"):
                score = meta.get(key)
                if score is not None:
                    break
        try:
            out.append({"score": float(score or 0.0)})
        except Exception:
            get_logger(__name__).debug("Skipping item after non-critical exception", exc_info=True)
            continue
    return out


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
    if ruleset_name is not None and ruleset_name.strip():
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
        if not text.strip():
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
        return _normalize_vector_hits(rows)

    hyde_text = hyde_query.strip() if hyde_query is not None else None
    verdict = verify_out_of_scope_query(
        query=query.strip(),
        glossary=glossary,
        keyword_search=_keyword_search,
        vector_search=_vector_search,
        hyde_generate=(lambda _q: hyde_text) if hyde_text is not None else None,
        vector_similarity_threshold=float(vector_similarity_threshold),
        hyde_similarity_threshold=float(hyde_similarity_threshold),
        enable_keyword=True,
        enable_vector=True,
        enable_hyde=bool(hyde_text),
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
    if not bool(enabled) or not bool(candidate) or not query.strip() or not tenant_id or not dataset_id:
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

    if verdict.get("verdict") == "out_of_scope":
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
]

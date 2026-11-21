"""Run evidence scope checks through the shared verdict policy and scoped storage adapters."""

from typing import Any, Mapping, Sequence
from uuid import UUID

from app.rag.industry_rules.loaders import load_ruleset
from app.rag.policy.out_of_scope_verifier import verify_out_of_scope_query
from app.rag.retrieval.corpus import CorpusScope, get_corpus_index
from app.storage.vector.factory import get_vector_store

_SCHEMA = "mimirq.out_of_scope_live_guard.v1"


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
        glossary = load_ruleset(ruleset_name).glossary

    def _keyword_search(text: str) -> Sequence[dict[str, Any]]:
        result = get_corpus_index().search(
            query=text,
            scope=CorpusScope(tenant_uuid, (dataset_uuid,)),
            top_k=3,
            metadata_filter={"dataset_id": str(dataset_uuid)},
        )
        return result.records

    def _vector_search(text: str) -> Sequence[dict[str, Any]]:
        if not text.strip():
            return []
        rows = get_vector_store().search(
            query=text,
            top_k=3,
            score_threshold=0.0,
            tenant_id=tenant_uuid,
            metadata_filter={"dataset_id": str(dataset_uuid)},
        )
        return [{"score": float(item.get("score") or 0.0)} for item in rows if isinstance(item, dict)]

    hyde_text = str(hyde_query if hyde_query is not None else "").strip()
    verdict = verify_out_of_scope_query(
        query=query.strip(),
        glossary=glossary,
        keyword_search=_keyword_search,
        vector_search=_vector_search,
        hyde_generate=lambda _q: hyde_text,
        vector_similarity_threshold=float(vector_similarity_threshold),
        hyde_similarity_threshold=float(hyde_similarity_threshold),
        enable_keyword=True,
        enable_vector=True,
        enable_hyde=bool(hyde_text),
    )
    return {"schema": _SCHEMA, **verdict}


__all__ = [
    "run_default_out_of_scope_live_guard",
]

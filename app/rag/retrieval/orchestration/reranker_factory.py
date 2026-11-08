"""Lightweight reranker factory shim for retrieval orchestration."""

from typing import Any

from app.rag.reranker.capabilities import describe_reranker_provider
from app.rag.reranker.registry import get_reranker_provider_family
from app.rag.reranker.types import RerankCandidate, RerankResult, SyncReranker


class _IdentityReranker:
    def __init__(self, provider: str | None = None) -> None:
        self.provider = str((provider if provider else "none")).strip().lower() or "none"
        self.model_name = None

    def rerank(self, query: str, candidates: list[RerankCandidate], **kwargs: Any) -> RerankResult:  # noqa: ARG002
        ordered_ids: list[str] = []
        score_map: dict[str, float] = {}
        for candidate in candidates:
            candidate_id = candidate.id.strip()
            if not candidate_id:
                continue
            ordered_ids.append(candidate_id)
            metadata = candidate.metadata
            score_value = metadata.get("score") or metadata.get("retrieval_score") or 0.0
            try:
                score_map[candidate_id] = float(score_value)
            except (OverflowError, TypeError, ValueError):
                score_map[candidate_id] = 0.0
        return RerankResult(
            ordered_ids=ordered_ids,
            score_map=score_map,
            items=[],
            clues=[],
            stats={"fallback": "identity"},
            elapsed_sec=0.0,
            model_used=None,
            provider=self.provider,
        )


def get_reranker(provider: str | None = None, **kwargs: Any) -> SyncReranker:
    provider_family = get_reranker_provider_family(provider)
    if not provider or not provider.strip() or (provider_family and provider_family.canonical_name == "none"):
        return _IdentityReranker(provider=provider)

    try:
        from app.rag.reranker.factory import get_reranker as _real_get_reranker

        return _real_get_reranker(provider, **kwargs)
    except ModuleNotFoundError:
        return _IdentityReranker(provider=provider)


__all__ = ["describe_reranker_provider", "get_reranker"]

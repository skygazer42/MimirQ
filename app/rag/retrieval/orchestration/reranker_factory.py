"""Lightweight reranker factory shim for retrieval orchestration."""

from typing import Any

from app.rag.reranker.capabilities import describe_reranker_provider
from app.rag.reranker.types import RerankCandidate, RerankResult


class _IdentityReranker:
    def __init__(self, provider: str | None = None) -> None:
        self.provider = str(provider or "none").strip().lower() or "none"
        self.model_name = None

    def rerank(self, query: str, candidates: list[RerankCandidate], **kwargs: Any) -> RerankResult:  # noqa: ARG002
        ordered_ids = [
            str(getattr(c, "id", "") or "").strip() for c in candidates if str(getattr(c, "id", "") or "").strip()
        ]
        score_map: dict[str, float] = {}
        for candidate in candidates:
            cid = str(getattr(candidate, "id", "") or "").strip()
            if not cid:
                continue
            meta = getattr(candidate, "metadata", None)
            meta = meta if isinstance(meta, dict) else {}
            try:
                score = float(meta.get("score") or meta.get("retrieval_score") or 0.0)
            except Exception:
                score = 0.0
            score_map[cid] = score
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


def get_reranker(provider: str | None = None, **kwargs: Any):  # noqa: ANN401
    try:
        from app.rag.reranker.factory import get_reranker as _real_get_reranker

        return _real_get_reranker(provider, **kwargs)
    except Exception:
        return _IdentityReranker(provider=provider)


__all__ = ["describe_reranker_provider", "get_reranker"]

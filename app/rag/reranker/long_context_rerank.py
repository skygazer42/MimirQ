from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from app.rag.reranker.types import RerankCandidate, RerankResult


def rerank_long_context_candidates(
    *,
    query: str,
    candidates: Sequence[RerankCandidate],
    scorer: Callable[[str, list[RerankCandidate]], dict[str, float]],
    top_n: int = 20,
) -> RerankResult:
    docs = list(candidates or [])
    scores = dict(scorer(str(query or ""), docs) or {})
    ordered_ids = sorted(
        [doc.id for doc in docs],
        key=lambda cid: (float(scores.get(cid, 0.0)), cid),
        reverse=True,
    )[: max(1, int(top_n or 1))]
    return RerankResult(
        ordered_ids=ordered_ids,
        score_map={cid: float(scores.get(cid, 0.0)) for cid in ordered_ids},
        stats={
            "mode": "long_context",
            "candidates_considered": len(docs),
            "top_n": max(1, int(top_n or 1)),
        },
    )

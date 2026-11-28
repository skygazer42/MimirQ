import logging
from collections.abc import Callable, Sequence
from typing import Any

from app.rag.ingestion.governance.text.tokenization import tokenize_lexical_text
from app.rag.retrieval.reranking.base import BaseReranker
from app.rag.retrieval.reranking.types import RerankCandidate, RerankResult

logger = logging.getLogger("app.rag.reranker.long_context_rerank")


def rerank_long_context_candidates(
    *,
    query: str,
    candidates: Sequence[RerankCandidate],
    scorer: Callable[[str, list[RerankCandidate]], dict[str, float]],
    top_n: int = 20,
) -> RerankResult:
    docs = list(candidates)
    scores = scorer(query, docs)
    limit = max(1, top_n)
    ordered_ids = sorted(
        [doc.id for doc in docs],
        key=lambda cid: (float(scores.get(cid, 0.0)), cid),
        reverse=True,
    )[:limit]
    return RerankResult(
        ordered_ids=ordered_ids,
        score_map={cid: float(scores.get(cid, 0.0)) for cid in ordered_ids},
        stats={
            "mode": "long_context",
            "candidates_considered": len(docs),
            "top_n": limit,
        },
    )


def _default_long_context_scorer(query: str, docs: list[RerankCandidate]) -> dict[str, float]:
    query_tokens = [token for token in tokenize_lexical_text(query) if token]
    if not query_tokens:
        return {doc.id: 0.0 for doc in docs}
    query_terms = set(query_tokens)

    doc_tokens: dict[str, set[str]] = {}
    df: dict[str, int] = dict.fromkeys(query_tokens, 0)
    for doc in docs:
        tokens = set(tokenize_lexical_text(doc.text))
        doc_tokens[doc.id] = tokens
        for token in query_tokens:
            if token in tokens:
                df[token] += 1

    out: dict[str, float] = {}
    for idx, doc in enumerate(docs):
        doc_id = doc.id
        overlap = query_terms & doc_tokens[doc_id]
        if not overlap:
            out[doc_id] = 0.0
            continue

        score = 0.0
        for token in overlap:
            score += 1.0 / df[token]

        chunk_index = doc.metadata.get("chunk_index")
        if chunk_index is not None:
            try:
                score += max(0.0, 0.05 - min(0.05, float(int(chunk_index)) * 0.001))
            except (OverflowError, TypeError, ValueError) as exc:
                logger.debug("Ignoring long-context chunk index score adjustment failure: %s", exc)
        score += max(0.0, 0.01 - float(idx) * 0.0001)
        out[doc_id] = round(score, 6)
    return out


class LongContextReranker(BaseReranker):
    def __init__(
        self,
        *,
        scorer: Callable[[str, list[RerankCandidate]], dict[str, float]] | None = None,
        model_name: str | None = None,
    ) -> None:
        self._scorer = scorer if scorer is not None else _default_long_context_scorer
        self.model_name = "long_context:deterministic" if model_name is None else model_name.strip()

    def rerank(
        self,
        query: str,
        candidates: Sequence[RerankCandidate],
        **kwargs: Any,
    ) -> RerankResult:
        out = rerank_long_context_candidates(
            query=query,
            candidates=candidates,
            scorer=self._scorer,
            top_n=max(1, int(kwargs.get("top_n") or 20)),
        )
        out.provider = "long_context"
        out.model_used = self.model_name
        return out


__all__ = ["LongContextReranker", "rerank_long_context_candidates"]

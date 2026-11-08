from collections.abc import Callable, Sequence
from typing import Any

from app.rag.core.logging import get_logger
from app.rag.preprocessing.tokenization import tokenize_lexical_text
from app.rag.reranker.base import BaseReranker
from app.rag.reranker.types import RerankCandidate, RerankResult

logger = get_logger(__name__)


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


def _default_long_context_scorer(query: str, docs: list[RerankCandidate]) -> dict[str, float]:
    query_tokens = [str(tok).strip() for tok in tokenize_lexical_text(str(query or "")) if str(tok).strip()]
    if not query_tokens:
        return {str(doc.id): 0.0 for doc in (docs or [])}

    doc_tokens: dict[str, set[str]] = {}
    df: dict[str, int] = dict.fromkeys(query_tokens, 0)
    for doc in docs or []:
        tokens = set(tokenize_lexical_text(str(doc.text or "")))
        doc_tokens[str(doc.id)] = tokens
        for token in query_tokens:
            if token in tokens:
                df[token] += 1

    out: dict[str, float] = {}
    for idx, doc in enumerate(docs or []):
        doc_id = str(doc.id)
        overlap = set(query_tokens) & doc_tokens.get(doc_id, set())
        if not overlap:
            out[doc_id] = 0.0
            continue

        score = 0.0
        for token in overlap:
            score += 1.0 / max(1, df[token] or 1)

        chunk_index = (doc.metadata or {}).get("chunk_index")
        if chunk_index is not None:
            try:
                score += max(0.0, 0.05 - min(0.05, float(int(chunk_index)) * 0.001))
            except Exception as exc:
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
            query=str(query or ""),
            candidates=list(candidates or []),
            scorer=self._scorer,
            top_n=max(1, int(kwargs.get("top_n") or 20)),
        )
        out.provider = "long_context"
        out.model_used = self.model_name
        return out


__all__ = ["LongContextReranker", "rerank_long_context_candidates"]

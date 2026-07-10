
from collections.abc import Sequence
from typing import Any

from app.rag.preprocessing.tokenization import tokenize_for_bm25
from app.rag.reranker.base import BaseReranker
from app.rag.reranker.types import RerankCandidate, RerankResult


def _token_set(text: str) -> set[str]:
    return {str(tok).strip() for tok in tokenize_for_bm25(str(text or "")) if str(tok).strip()}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    if union <= 0:
        return 0.0
    return float(inter) / float(union)


class MMRReranker(BaseReranker):
    def __init__(self, *, lambda_mult: float = 0.7) -> None:
        self.lambda_mult = max(0.0, min(1.0, float(lambda_mult or 0.0)))

    def rerank(
        self,
        query: str,
        candidates: Sequence[RerankCandidate],
        **kwargs: Any,
    ) -> RerankResult:
        docs = list(candidates or [])
        top_n = max(1, int(kwargs.get("top_n") or len(docs) or 1))
        query_tokens = _token_set(str(query or ""))
        doc_tokens = {str(doc.id): _token_set(doc.text or "") for doc in docs}
        relevance = {str(doc.id): _jaccard(query_tokens, doc_tokens.get(str(doc.id), set())) for doc in docs}

        remaining = [str(doc.id) for doc in docs]
        selected: list[str] = []
        score_map: dict[str, float] = {}
        while remaining and len(selected) < top_n:
            best_id = ""
            best_score = float("-inf")
            for candidate_id in remaining:
                rel = float(relevance.get(candidate_id, 0.0) or 0.0)
                if not selected:
                    mmr_score = rel
                else:
                    diversity_penalty = max(
                        _jaccard(doc_tokens.get(candidate_id, set()), doc_tokens.get(selected_id, set()))
                        for selected_id in selected
                    )
                    mmr_score = self.lambda_mult * rel - (1.0 - self.lambda_mult) * diversity_penalty
                if mmr_score > best_score:
                    best_score = mmr_score
                    best_id = candidate_id
            if not best_id:
                break
            selected.append(best_id)
            score_map[best_id] = float(best_score)
            remaining = [candidate_id for candidate_id in remaining if candidate_id != best_id]

        return RerankResult(
            ordered_ids=selected,
            score_map=score_map,
            stats={
                "mode": "mmr",
                "lambda_mult": float(self.lambda_mult),
                "candidates_considered": len(docs),
                "top_n": int(top_n),
            },
            provider="mmr",
            model_used="mmr:lexical",
        )


__all__ = ["MMRReranker"]

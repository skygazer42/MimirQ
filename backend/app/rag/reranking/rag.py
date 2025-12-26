from __future__ import annotations

from typing import Optional, Sequence

from app.models.dify import Document as DifyDocument
from app.rag.reranking.llm_reranker import get_llm_reranker
from app.rag.reranking.rerankers import ParentChildRerankRunner
from app.rag.reranking.types import RerankCandidate, RerankResult


class RagLlmReranker:
    def rerank(
        self,
        query: str,
        candidates: Sequence[RerankCandidate],
        **kwargs: object,
    ) -> RerankResult:
        payload = []
        for c in candidates:
            cid = str(c.id).strip()
            text = (c.text or "").strip()
            if not cid or not text:
                continue
            payload.append({"id": cid, "text": text})

        reranker = get_llm_reranker()
        result = reranker.rerank(query=query, candidates=payload)
        return RerankResult(
            ordered_ids=result.ordered_ids,
            score_map=result.score_map,
            elapsed_sec=result.elapsed_sec,
            model_used=result.model_used,
            provider="llm",
        )


class RagParentChildReranker:
    def __init__(self) -> None:
        self._runner = ParentChildRerankRunner()

    def rerank(
        self,
        query: str,
        candidates: Sequence[RerankCandidate],
        **kwargs: object,
    ) -> RerankResult:
        docs: list[DifyDocument] = []
        for c in candidates:
            cid = str(c.id).strip()
            text = (c.text or "").strip()
            if not cid or not text:
                continue
            meta = dict(c.metadata or {})
            meta.setdefault("candidate_id", cid)
            meta.setdefault("score", meta.get("score", 0.0))
            docs.append(DifyDocument(page_content=text, metadata=meta, provider="rag"))

        top_n = kwargs.get("top_n")
        score_threshold = kwargs.get("score_threshold")
        reranked = self._runner.run(query, docs, score_threshold=score_threshold, top_n=top_n)

        ordered_ids: list[str] = []
        score_map: dict[str, float] = {}
        for doc in reranked:
            meta = doc.metadata or {}
            cid = meta.get("candidate_id")
            if cid is None:
                continue
            cid = str(cid)
            ordered_ids.append(cid)
            score_map[cid] = float(meta.get("score", 0.0) or 0.0)

        return RerankResult(
            ordered_ids=ordered_ids,
            score_map=score_map,
            provider="pc",
        )


_rag_reranker_cache: dict[str, object] = {}


def get_rag_reranker(provider: Optional[str] = None) -> object:
    key = (provider or "llm").lower()
    cached = _rag_reranker_cache.get(key)
    if cached is not None:
        return cached

    if key == "pc":
        reranker: object = RagParentChildReranker()
    else:
        reranker = RagLlmReranker()

    _rag_reranker_cache[key] = reranker
    return reranker


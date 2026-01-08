"""
LLM-based reranker.

Reranks retrieved candidates to improve reference relevance.

Strategy:
- Input query + candidates (truncated text)
- Ask the LLM to output strict JSON: [{"id": "...", "score": 0~1}, ...], sorted by relevance
- Fall back to original order if parsing fails

Note: this module is a reranker implementation; do not confuse it with app.rag.llm (LLM client).
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import settings
from app.models.chunk import Document
from app.rag.core.http import httpx_trust_env
from app.rag.reranker.base import DocumentReranker


@dataclass
class LLMRerankResult:
    """LLM rerank result."""
    ordered_ids: list[str]
    score_map: dict[str, float]
    elapsed_sec: float
    model_used: str | None


def _build_http_clients() -> tuple[httpx.Client, httpx.AsyncClient]:
    """
    Reuse the same proxy handling as the RAG engine:
    - If a SOCKS proxy is detected, disable trust_env to avoid httpx issues.
    """
    trust_env = httpx_trust_env()
    return httpx.Client(trust_env=trust_env, timeout=settings.LLM_TIMEOUT), httpx.AsyncClient(
        trust_env=trust_env, timeout=settings.LLM_TIMEOUT
    )


def _extract_json_array(text: str) -> str | None:
    """Best-effort extract the JSON array portion from LLM output."""
    if not text:
        return None
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1 or end <= start:
        return None
    return text[start : end + 1]


class LLMReranker(DocumentReranker):
    """LLM reranker (document-level reranking via LLM)."""

    def __init__(self) -> None:
        from langchain_openai import ChatOpenAI
        from langchain_core.prompts import ChatPromptTemplate
        from langchain_core.output_parsers import StrOutputParser

        model_name = settings.RERANKER_MODEL or settings.LLM_MODEL_FAST or settings.LLM_MODEL
        http_client, http_async_client = _build_http_clients()

        self.model_used = model_name
        self._llm = ChatOpenAI(
            model=model_name,
            api_key=settings.LLM_API_KEY,
            base_url=settings.LLM_API_BASE,
            temperature=float(settings.RERANKER_TEMPERATURE or 0.0),
            streaming=False,
            timeout=settings.LLM_TIMEOUT,
            max_retries=settings.LLM_MAX_RETRIES,
            http_client=http_client,
            http_async_client=http_async_client,
        )

        self._prompt = ChatPromptTemplate.from_template(
            """你是一个"检索结果精排器"。给定 query 和候选文段 candidates，请输出严格 JSON 数组：
[{"id": "...", "score": 0.0}]

要求：
1) score 取 0~1，越大越相关；
2) 按 score 从高到低排序；
3) 只输出 JSON，不要输出任何解释、Markdown、代码块；
4) id 必须来自输入 candidates（不要新增/编造 id）。

query: {query}

candidates(JSON): {candidates}
"""
        )
        self._chain = self._prompt | self._llm | StrOutputParser()


    def _candidate_id(self, document: Document, fallback_idx: int) -> str:
        """Extract a candidate ID from a Document."""
        meta = document.metadata or {}
        for key in ("candidate_id", "doc_id", "chunk_id"):
            value = meta.get(key)
            if value:
                return str(value)
        doc_id = meta.get("document_id")
        chunk_index = meta.get("chunk_index")
        if doc_id is not None and chunk_index is not None:
            return f"{doc_id}:{chunk_index}"
        return f"idx:{fallback_idx}"

    def run(
        self,
        query: str,
        documents: list[Document],
        score_threshold: float | None = None,
        top_n: int | None = None,
        user: str | None = None,
    ) -> list[Document]:
        """
        Run LLM reranking.

        Args:
            query: query text
            documents: document list
            score_threshold: score threshold
            top_n: return top N results
            user: user identifier (unused)

        Returns:
            reranked document list
        """
        if not documents:
            return []

        candidates: list[dict[str, Any]] = []
        id_to_doc: dict[str, Document] = {}
        for idx, doc in enumerate(documents):
            text = (doc.page_content or "").strip()
            if not text:
                continue
            cid = self._candidate_id(doc, idx)
            candidates.append({"id": cid, "text": text})
            id_to_doc[cid] = doc

        if not candidates:
            return documents[:top_n] if top_n else documents

        result = self.rerank_raw(query=query, candidates=candidates)
        if not result.ordered_ids:
            return documents[:top_n] if top_n else documents

        ordered: list[Document] = []
        used: set[str] = set()
        for cid in result.ordered_ids:
            doc = id_to_doc.get(cid)
            if not doc or cid in used:
                continue
            used.add(cid)
            if doc.metadata is None:
                doc.metadata = {}
            if cid in result.score_map:
                doc.metadata["score"] = float(result.score_map[cid])
            if score_threshold is not None:
                score = doc.metadata.get("score")
                if score is not None and float(score) < score_threshold:
                    continue
            ordered.append(doc)
            if top_n and len(ordered) >= top_n:
                return ordered

        # Append documents that were not reranked.
        for idx, doc in enumerate(documents):
            cid = self._candidate_id(doc, idx)
            if cid in used:
                continue
            if score_threshold is not None:
                score = (doc.metadata or {}).get("score")
                if score is not None and float(score) < score_threshold:
                    continue
            ordered.append(doc)
            if top_n and len(ordered) >= top_n:
                break

        return ordered

    def rerank_raw(self, query: str, candidates: list[dict[str, Any]]) -> LLMRerankResult:
        """
        Call the LLM directly for reranking (raw interface).

        Args:
            query: query text
            candidates: candidate list [{id, text, ...}]

        Returns:
            LLMRerankResult with ordered IDs and score map
        """
        payload = []
        max_chars = int(settings.RERANKER_MAX_CHARS or 800)
        for c in candidates:
            cid = str(c.get("id") or "").strip()
            text = (c.get("text") or "").strip()
            if not cid or not text:
                continue
            if max_chars and len(text) > max_chars:
                text = text[:max_chars] + "..."
            payload.append({"id": cid, "text": text})

        if not payload:
            return LLMRerankResult(ordered_ids=[], score_map={}, elapsed_sec=0.0, model_used=self.model_used)

        start = time.time()
        out_text = self._chain.invoke(
            {
                "query": query,
                "candidates": json.dumps(payload, ensure_ascii=False),
            }
        )
        elapsed = time.time() - start

        json_text = _extract_json_array((out_text or "").strip())
        if not json_text:
            return LLMRerankResult(ordered_ids=[], score_map={}, elapsed_sec=elapsed, model_used=self.model_used)

        data = json.loads(json_text)

        ordered: list[str] = []
        score_map: dict[str, float] = {}
        for item in data if isinstance(data, list) else []:
            if not isinstance(item, dict):
                continue
            cid = str(item.get("id") or "").strip()
            if not cid:
                continue
            score = float(item.get("score", 0.0))
            score = max(min(score, 1.0), 0.0)
            if cid not in ordered:
                ordered.append(cid)
            score_map[cid] = score

        return LLMRerankResult(ordered_ids=ordered, score_map=score_map, elapsed_sec=elapsed, model_used=self.model_used)


_llm_reranker: LLMReranker | None = None


def get_llm_reranker() -> LLMReranker:
    """Get the LLM reranker singleton."""
    global _llm_reranker
    if _llm_reranker is None:
        _llm_reranker = LLMReranker()
    return _llm_reranker

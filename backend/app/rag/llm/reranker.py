"""
LLM Reranker（基于大模型的精排器）

用于对检索到的候选切片做"精排"，提升答案引用的相关性。
实现策略：
- 输入 query + candidates（截断后的 text）
- 让 LLM 输出严格 JSON：[{ "id": "...", "score": 0~1 }, ...]，按相关度降序
- 解析失败则回退到原顺序
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import httpx

from app.core.config import settings
from app.models.dify import Document
from app.rag.reranker.base import DocumentReranker


@dataclass
class LLMRerankResult:
    """LLM 重排结果"""
    ordered_ids: List[str]
    score_map: Dict[str, float]
    elapsed_sec: float
    model_used: Optional[str]


def _build_http_clients() -> tuple[httpx.Client, httpx.AsyncClient]:
    """
    复用与 RAG 引擎一致的 proxy 处理逻辑：
    - 如果检测到 SOCKS 代理，禁用 trust_env 避免 httpx 兼容问题。
    """
    proxy_candidates = [
        os.getenv("OPENAI_PROXY"),
        os.getenv("HTTPS_PROXY"),
        os.getenv("HTTP_PROXY"),
        os.getenv("ALL_PROXY"),
        os.getenv("https_proxy"),
        os.getenv("http_proxy"),
        os.getenv("all_proxy"),
    ]
    proxies = [p for p in proxy_candidates if p]
    trust_env = True
    socks_proxy = next((p for p in proxies if p.lower().startswith("socks")), None)
    if socks_proxy:
        trust_env = False
    return httpx.Client(trust_env=trust_env, timeout=settings.LLM_TIMEOUT), httpx.AsyncClient(
        trust_env=trust_env, timeout=settings.LLM_TIMEOUT
    )


def _extract_json_array(text: str) -> Optional[str]:
    """从 LLM 输出中尽量提取 JSON 数组部分。"""
    if not text:
        return None
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1 or end <= start:
        return None
    return text[start : end + 1]


class LLMReranker(DocumentReranker):
    """LLM 精排器（基于大模型的文档重排）"""

    def __init__(self) -> None:
        try:
            from langchain_openai import ChatOpenAI
            from langchain_core.prompts import ChatPromptTemplate
            from langchain_core.output_parsers import StrOutputParser
        except Exception as exc:  # pragma: no cover
            raise RuntimeError(
                "LLM reranker requires langchain_openai. Please install backend requirements."
            ) from exc

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
        """从 Document 中提取候选 ID"""
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
        运行 LLM 重排
        
        Args:
            query: 查询文本
            documents: 文档列表
            score_threshold: 分数阈值
            top_n: 返回前 N 个结果
            user: 用户标识（未使用）
            
        Returns:
            重排后的文档列表
        """
        if not documents:
            return []

        candidates: List[Dict[str, Any]] = []
        id_to_doc: Dict[str, Document] = {}
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

        ordered: List[Document] = []
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

        # 添加未重排的文档
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

    def rerank_raw(self, query: str, candidates: List[Dict[str, Any]]) -> LLMRerankResult:
        """
        直接调用 LLM 进行重排（原始接口）
        
        Args:
            query: 查询文本
            candidates: 候选列表 [{id, text, ...}]
            
        Returns:
            LLMRerankResult: 包含排序后的 ID 列表和分数映射
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

        try:
            data = json.loads(json_text)
        except Exception:
            return LLMRerankResult(ordered_ids=[], score_map={}, elapsed_sec=elapsed, model_used=self.model_used)

        ordered: List[str] = []
        score_map: Dict[str, float] = {}
        for item in data if isinstance(data, list) else []:
            if not isinstance(item, dict):
                continue
            cid = str(item.get("id") or "").strip()
            if not cid:
                continue
            try:
                score = float(item.get("score", 0.0))
            except Exception:
                score = 0.0
            score = max(min(score, 1.0), 0.0)
            if cid not in ordered:
                ordered.append(cid)
            score_map[cid] = score

        return LLMRerankResult(ordered_ids=ordered, score_map=score_map, elapsed_sec=elapsed, model_used=self.model_used)


_reranker_singleton: Optional[LLMReranker] = None


def get_llm_reranker() -> LLMReranker:
    """获取 LLM Reranker 单例"""
    global _reranker_singleton
    if _reranker_singleton is None:
        _reranker_singleton = LLMReranker()
    return _reranker_singleton


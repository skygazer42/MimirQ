"""
Reranker 基类

统一的 Reranker 架构：
- BaseReranker: 顶层抽象基类，定义统一的 rerank() 接口
- APIReranker: 用于 HTTP API 调用的 reranker（如 OpenAI, DashScope）
- DocumentReranker: 用于文档级别重排的 reranker（如 Weight, ParentChild, LLM）
"""
from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Sequence

import aiohttp
import numpy as np

from app.rag.reranker.types import RerankCandidate, RerankResult


def sigmoid(x: float) -> float:
    """Sigmoid 归一化函数"""
    return 1 / (1 + np.exp(-x))


class BaseReranker(ABC):
    """
    Reranker 顶层抽象基类
    
    所有 reranker 的统一接口，定义 rerank() 方法。
    子类可以选择实现同步或异步版本。
    """

    @abstractmethod
    def rerank(
        self,
        query: str,
        candidates: Sequence[RerankCandidate],
        **kwargs: Any,
    ) -> RerankResult:
        """
        同步重排接口
        
        Args:
            query: 查询文本
            candidates: 候选列表
            **kwargs: 其他参数（如 top_n, score_threshold）
            
        Returns:
            RerankResult: 重排结果
        """
        raise NotImplementedError

    async def arerank(
        self,
        query: str,
        candidates: Sequence[RerankCandidate],
        **kwargs: Any,
    ) -> RerankResult:
        """
        异步重排接口（可选）
        
        默认实现：在独立线程中运行同步 rerank()
        子类可以覆盖提供真正的异步实现。
        """
        import concurrent.futures
        
        loop = asyncio.get_event_loop()
        with concurrent.futures.ThreadPoolExecutor() as pool:
            return await loop.run_in_executor(pool, self.rerank, query, candidates, kwargs)


class APIReranker(BaseReranker):
    """
    HTTP API 调用型 Reranker 抽象基类
    
    用于调用远程 reranker API（如 OpenAI, DashScope, SiliconFlow 等）。
    子类需要实现：
    - _build_payload(): 构建请求体
    - _extract_results(): 解析响应结果
    """

    def __init__(
        self,
        model_name: str,
        api_key: str,
        base_url: str,
        timeout: float = 30.0,
        **kwargs,
    ):
        self.url = base_url
        self.model = model_name
        self.api_key = api_key
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        self.session: aiohttp.ClientSession | None = None
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self.parameters: Dict[str, Any] = dict(kwargs.get("parameters", {}))

    async def _ensure_session(self) -> None:
        """确保 aiohttp session 可用"""
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(
                headers=self.headers,
                timeout=self.timeout,
            )

    @abstractmethod
    def _build_payload(
        self,
        query: str,
        documents: List[str],
        max_length: int,
    ) -> Dict[str, Any]:
        """构建请求体，子类实现"""
        raise NotImplementedError

    @abstractmethod
    def _extract_results(self, result: Dict[str, Any]) -> List[Dict[str, Any]]:
        """解析响应结果，子类实现"""
        raise NotImplementedError

    async def acompute_score(
        self,
        query: str,
        documents: List[str],
        batch_size: int = 32,
        max_length: int = 512,
        normalize: bool = True,
    ) -> List[float]:
        """
        异步计算重排分数

        Args:
            query: 查询文本
            documents: 文档列表
            batch_size: 批次大小
            max_length: 最大长度
            normalize: 是否归一化分数

        Returns:
            分数列表，与 documents 顺序对应
        """
        if not documents:
            return []

        await self._ensure_session()

        all_scores: List[float] = []
        batch_size = max(1, int(batch_size))

        for start in range(0, len(documents), batch_size):
            batch = documents[start : start + batch_size]
            scores = await self._batch_rerank(query, batch, max_length=max_length)
            all_scores.extend(scores)

        if normalize:
            all_scores = [float(sigmoid(score)) for score in all_scores]

        return all_scores

    async def _batch_rerank(
        self,
        query: str,
        documents: List[str],
        max_length: int,
    ) -> List[float]:
        """单批次重排"""
        if not documents:
            return []

        payload = self._build_payload(query, documents, max_length)

        await self._ensure_session()
        assert self.session is not None

        async with self.session.post(self.url, json=payload) as response:
            response.raise_for_status()
            result: Dict[str, Any] = await response.json()

        processed = sorted(
            self._extract_results(result),
            key=lambda item: item.get("index", 0),
        )
        return [float(entry.get("relevance_score", 0.0)) for entry in processed]

    def compute_score(
        self,
        query: str,
        documents: List[str],
        batch_size: int = 32,
        max_length: int = 512,
        normalize: bool = True,
    ) -> List[float]:
        """同步计算重排分数"""
        try:
            _ = asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(
                self.acompute_score(query, documents, batch_size, max_length, normalize)
            )
        raise RuntimeError(
            "compute_score cannot be used while an event loop is running. "
            "Use acompute_score instead."
        )

    def rerank(
        self,
        query: str,
        candidates: Sequence[RerankCandidate],
        **kwargs: Any,
    ) -> RerankResult:
        """
        同步重排接口（实现 BaseReranker）
        
        将候选转换为文档列表，调用 API 计算分数。
        """
        if not candidates:
            return RerankResult(ordered_ids=[], score_map={})
        
        documents = [c.text for c in candidates]
        scores = self.compute_score(query, documents)
        
        # 构建结果
        score_map = {c.id: score for c, score in zip(candidates, scores)}
        ordered_candidates = sorted(
            zip(candidates, scores),
            key=lambda x: x[1],
            reverse=True
        )
        ordered_ids = [c.id for c, _ in ordered_candidates]
        
        top_n = kwargs.get("top_n")
        if top_n:
            ordered_ids = ordered_ids[:top_n]
            score_map = {cid: score_map[cid] for cid in ordered_ids}
        
        return RerankResult(
            ordered_ids=ordered_ids,
            score_map=score_map,
            model_used=self.model,
            provider=self.__class__.__name__.replace("Reranker", "").lower(),
        )

    async def arerank_legacy(
        self,
        query: str,
        candidates: Sequence[Dict[str, Any]],
        top_n: int | None = None,
    ) -> List[Dict[str, Any]]:
        """
        异步重排候选文档（旧版接口，保持向后兼容）

        Args:
            query: 查询文本
            candidates: 候选文档列表，每个包含 id, text, metadata
            top_n: 返回 top N 结果

        Returns:
            重排后的候选列表，按分数降序
        """
        if not candidates:
            return []

        documents = [c.get("text", "") for c in candidates]
        scores = await self.acompute_score(query, documents)

        results = []
        for candidate, score in zip(candidates, scores):
            result = dict(candidate)
            result["rerank_score"] = score
            results.append(result)

        results.sort(key=lambda x: x.get("rerank_score", 0), reverse=True)

        if top_n:
            results = results[:top_n]

        return results

    async def aclose(self) -> None:
        """关闭 session"""
        if self.session and not self.session.closed:
            await self.session.close()

    def __del__(self) -> None:
        if self.session and not self.session.closed:
            try:
                loop = asyncio.get_event_loop()
            except RuntimeError:
                asyncio.run(self.aclose())
                return

            if loop.is_closed():
                asyncio.run(self.aclose())
            elif not loop.is_running():
                loop.run_until_complete(self.aclose())


class DocumentReranker(BaseReranker):
    """
    文档级别 Reranker 抽象基类
    
    用于对文档列表进行重排（如权重融合、父子关系、LLM 精排等）。
    子类需要实现 run() 方法。
    """

    @abstractmethod
    def run(
        self,
        query: str,
        documents: List[Any],
        score_threshold: float | None = None,
        top_n: int | None = None,
        user: str | None = None,
    ) -> List[Any]:
        """
        运行重排模型，返回按相关性排序的文档列表
        
        Args:
            query: 查询文本
            documents: 文档列表（通常是 Document 对象）
            score_threshold: 分数阈值
            top_n: 返回前 N 个结果
            user: 用户标识（可选）
            
        Returns:
            重排后的文档列表
        """
        raise NotImplementedError

    def rerank(
        self,
        query: str,
        candidates: Sequence[RerankCandidate],
        **kwargs: Any,
    ) -> RerankResult:
        """
        同步重排接口（实现 BaseReranker）
        
        将 RerankCandidate 转换为 Document 对象，调用 run() 方法。
        """
        from app.models.dify import Document as DifyDocument
        
        if not candidates:
            return RerankResult(ordered_ids=[], score_map={})
        
        # 转换为 Document 对象
        docs: List[DifyDocument] = []
        for c in candidates:
            meta = dict(c.metadata or {})
            meta.setdefault("candidate_id", c.id)
            docs.append(
                DifyDocument(
                    page_content=c.text,
                    metadata=meta,
                    provider="reranker"
                )
            )
        
        # 调用 run 方法
        top_n = kwargs.get("top_n")
        score_threshold = kwargs.get("score_threshold")
        reranked = self.run(query, docs, score_threshold=score_threshold, top_n=top_n)
        
        # 提取结果
        ordered_ids: List[str] = []
        score_map: Dict[str, float] = {}
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
            provider=self.__class__.__name__.replace("Reranker", "").lower(),
        )

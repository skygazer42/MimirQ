"""
Reranker 基类

参考 Yuxi-Know 的设计模式：抽象基类 + 具体实现。
"""
from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Sequence

import aiohttp
import numpy as np

from app.core.config import settings


def sigmoid(x: float) -> float:
    """Sigmoid 归一化函数"""
    return 1 / (1 + np.exp(-x))


class BaseReranker(ABC):
    """
    Reranker 抽象基类

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
            try:
                scores = await self._batch_rerank(query, batch, max_length=max_length)
                all_scores.extend(scores)
            except Exception as exc:
                print(f"[WARN] Reranking batch failed: {exc}")
                all_scores.extend([0.5] * len(batch))

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

    async def arerank(
        self,
        query: str,
        candidates: Sequence[Dict[str, Any]],
        top_n: int | None = None,
    ) -> List[Dict[str, Any]]:
        """
        异步重排候选文档

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

"""
Reranker 模块

提供多种重排器实现：
- BaseReranker: 抽象基类
- OpenAIReranker: OpenAI 风格 API
- DashScopeReranker: 阿里云 DashScope
- LLMReranker: 基于 LLM 的重排
- WeightReranker: 权重融合重排
"""
from app.rag.reranker.base import BaseReranker
from app.rag.reranker.openai import OpenAIReranker
from app.rag.reranker.dashscope import DashScopeReranker
from app.rag.reranker.types import RerankCandidate, RerankResult

__all__ = [
    "BaseReranker",
    "OpenAIReranker",
    "DashScopeReranker",
    "RerankCandidate",
    "RerankResult",
    "get_reranker",
]


def get_reranker(
    provider: str,
    model_name: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    **kwargs,
) -> BaseReranker:
    """
    获取 Reranker 实例

    Args:
        provider: 提供商 (openai, dashscope, siliconflow, vllm)
        model_name: 模型名称
        api_key: API Key
        base_url: API Base URL
        **kwargs: 其他参数

    Returns:
        Reranker 实例
    """
    from app.core.config import settings

    provider = (provider or "").lower()
    model_name = model_name or settings.RERANKER_MODEL or "BAAI/bge-reranker-v2-m3"
    api_key = api_key or settings.RERANKER_API_KEY or settings.LLM_API_KEY
    base_url = base_url or settings.RERANKER_API_BASE or settings.LLM_API_BASE

    if provider in ("dashscope", "aliyun"):
        return DashScopeReranker(
            model_name=model_name,
            api_key=api_key,
            base_url=base_url or "https://dashscope.aliyuncs.com/api/v1/services/rerank",
            **kwargs,
        )

    # 默认使用 OpenAI 风格 API
    return OpenAIReranker(
        model_name=model_name,
        api_key=api_key,
        base_url=base_url,
        **kwargs,
    )

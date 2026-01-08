"""
Reranker 工厂函数

提供统一的 reranker 创建接口。
"""
from __future__ import annotations

from typing import Any
import hashlib
import threading

from app.rag.reranker.base import BaseReranker
from app.core.config import settings

_api_reranker_lock = threading.Lock()
_api_reranker_cache: dict[str, BaseReranker] = {}


def _api_cache_key(provider: str, *, model: str, base_url: str, api_key: str) -> str:
    key_hash = hashlib.sha256((api_key or "").encode("utf-8", errors="ignore")).hexdigest()[:12]
    return f"{provider}:{model}:{base_url}:{key_hash}"


def get_reranker(
    provider: str,
    model_name: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    **kwargs: Any,
) -> BaseReranker:
    """
    获取 Reranker 实例（统一工厂函数）

    Args:
        provider: 提供商类型
            - 'openai': OpenAI 风格 API
            - 'dashscope'/'aliyun': 阿里云 DashScope
            - 'llm': 基于大模型的精排
            - 'weighted': 加权融合重排
            - 'parent_child'/'pc': 父子关系重排
            - 'kg_pagerank': 知识图谱 PageRank 重排
            - 'kg_rrf': 知识图谱 RRF 重排
        model_name: 模型名称（API reranker 需要）
        api_key: API Key（API reranker 需要）
        base_url: API Base URL（API reranker 需要）
        **kwargs: 其他参数

    Returns:
        BaseReranker 实例
    """
    

    provider = (provider or "").lower()

    # API Rerankers
    if provider in ("dashscope", "aliyun"):
        from app.rag.reranker.dashscope import DashScopeReranker
        
        model_name = model_name or settings.RERANKER_MODEL or "BAAI/bge-reranker-v2-m3"
        api_key = api_key or settings.RERANKER_API_KEY or settings.LLM_API_KEY
        base_url = base_url or "https://dashscope.aliyuncs.com/api/v1/services/rerank"
        
        timeout = float(kwargs.get("timeout") or settings.RERANKER_API_TIMEOUT_SEC or 30.0)
        kwargs_copy = {k: v for k, v in kwargs.items() if k != "timeout"}
        cache_key = _api_cache_key(provider, model=model_name, base_url=base_url, api_key=api_key)
        with _api_reranker_lock:
            cached = _api_reranker_cache.get(cache_key)
            if cached is not None:
                return cached
            inst = DashScopeReranker(
                model_name=model_name,
                api_key=api_key,
                base_url=base_url,
                timeout=timeout,
                **kwargs_copy,
            )
            _api_reranker_cache[cache_key] = inst
            return inst
    
    elif provider == "openai":
        from app.rag.reranker.openai import OpenAIReranker
        
        model_name = model_name or settings.RERANKER_MODEL or "BAAI/bge-reranker-v2-m3"
        api_key = api_key or settings.RERANKER_API_KEY or settings.LLM_API_KEY
        base_url = base_url or settings.RERANKER_API_BASE or settings.LLM_API_BASE
        
        timeout = float(kwargs.get("timeout") or settings.RERANKER_API_TIMEOUT_SEC or 30.0)
        kwargs_copy = {k: v for k, v in kwargs.items() if k != "timeout"}
        cache_key = _api_cache_key(provider, model=model_name, base_url=base_url, api_key=api_key)
        with _api_reranker_lock:
            cached = _api_reranker_cache.get(cache_key)
            if cached is not None:
                return cached
            inst = OpenAIReranker(
                model_name=model_name,
                api_key=api_key,
                base_url=base_url,
                timeout=timeout,
                **kwargs,
            )
            _api_reranker_cache[cache_key] = inst
            return inst
    
    # Document Rerankers
    elif provider == "llm":
        from app.rag.reranker.llm_based import get_llm_reranker
        return get_llm_reranker()
    
    elif provider in ("parent_child", "pc"):
        from app.rag.reranker.parent_child import ParentChildReranker
        return ParentChildReranker()
    
    elif provider == "weighted":
        from app.rag.reranker.hybrid import WeightedReranker
        
        weights = kwargs.get("weights")
        if not weights:
            raise ValueError("WeightedReranker requires 'weights' parameter")
        
        tenant_id = kwargs.get("tenant_id", "")
        embedding_fn = kwargs.get("embedding_fn")
        
        return WeightedReranker(
            tenant_id=tenant_id,
            weights=weights,
            embedding_fn=embedding_fn,
        )
    
    # KG Rerankers
    elif provider in ("kg_pagerank", "kg_rrf"):
        from app.rag.kg.search.config import RerankStrategy
        from app.rag.reranker.kg import KGReranker
        
        strategy = RerankStrategy.PAGERANK if provider == "kg_pagerank" else RerankStrategy.RRF
        return KGReranker(strategy)
    
    # 默认使用 OpenAI 风格 API
    else:
        from app.rag.reranker.openai import OpenAIReranker
        
        model_name = model_name or settings.RERANKER_MODEL or "BAAI/bge-reranker-v2-m3"
        api_key = api_key or settings.RERANKER_API_KEY or settings.LLM_API_KEY
        base_url = base_url or settings.RERANKER_API_BASE or settings.LLM_API_BASE
        
        timeout = float(kwargs.get("timeout") or settings.RERANKER_API_TIMEOUT_SEC or 30.0)
        kwargs_copy = {k: v for k, v in kwargs.items() if k != "timeout"}
        cache_key = _api_cache_key("openai", model=model_name, base_url=base_url, api_key=api_key)
        with _api_reranker_lock:
            cached = _api_reranker_cache.get(cache_key)
            if cached is not None:
                return cached
            inst = OpenAIReranker(
                model_name=model_name,
                api_key=api_key,
                base_url=base_url,
                timeout=timeout,
                **kwargs_copy,
            )
            _api_reranker_cache[cache_key] = inst
            return inst


# 向后兼容：旧的工厂函数（保留一段时间）
def get_rag_reranker(provider: str | None = None) -> BaseReranker:
    """
    获取 RAG Reranker（旧接口，已废弃）
    
    请使用 get_reranker() 替代。
    """
    import warnings
    warnings.warn(
        "get_rag_reranker() is deprecated, use get_reranker() instead",
        DeprecationWarning,
        stacklevel=2
    )
    
    provider = (provider or "llm").lower()
    if provider == "pc":
        return get_reranker("parent_child")
    else:
        return get_reranker("llm")


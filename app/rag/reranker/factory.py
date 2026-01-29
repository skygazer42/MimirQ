"""
Reranker factory functions.

Provide a unified reranker creation interface.
"""

import hashlib
import threading
from typing import Any

from app.core.config import settings
from app.rag.reranker.base import BaseReranker

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
    Get a reranker instance (unified factory).

    Args:
        provider: provider type
            - 'openai': OpenAI-style API
            - 'dashscope'/'aliyun': Alibaba Cloud DashScope
            - 'llm': LLM-based reranking
            - 'weighted': weighted hybrid reranking
            - 'parent_child'/'pc': parent-child reranking
            - 'kg_pagerank': knowledge graph PageRank reranking
            - 'kg_rrf': knowledge graph RRF reranking
        model_name: model name (required for API rerankers)
        api_key: API key (required for API rerankers)
        base_url: API base URL (required for API rerankers)
        **kwargs: other parameters

    Returns:
        BaseReranker instance
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
    
    # Default to OpenAI-style API.
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


# Backward compatibility: legacy factory function (kept for a while).
def get_rag_reranker(provider: str | None = None) -> BaseReranker:
    """
    Get the RAG reranker (legacy interface, deprecated).

    Use get_reranker() instead.
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

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
_local_reranker_lock = threading.Lock()
_local_reranker_cache: dict[str, BaseReranker] = {}


def _api_cache_key(provider: str, *, model: str, base_url: str, api_key: str) -> str:
    key_hash = hashlib.sha256((api_key or "").encode("utf-8", errors="ignore")).hexdigest()[:12]
    return f"{provider}:{model}:{base_url}:{key_hash}"


def _local_cache_key(provider: str, parts: list[str]) -> str:
    payload = "|".join([str(provider or "").lower().strip()] + [str(p or "") for p in (parts or [])])
    digest = hashlib.sha256(payload.encode("utf-8", errors="ignore")).hexdigest()[:16]
    return f"{provider}:{digest}"


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

    # Late-interaction reranker (ColBERT-style, local scaffold)
    elif provider in ("colbert", "late_interaction"):
        from app.rag.reranker.colbert import ColBERTReranker

        return ColBERTReranker()

    # Learning-to-Rank reranker (local xgboost model).
    elif provider in ("ltr", "xgboost_ltr"):
        from app.rag.reranker.ltr import LTRFeatureSpec, LTRReranker

        model_path = str(kwargs.get("model_path") or "").strip() or str(getattr(settings, "LTR_MODEL_PATH", "") or "").strip()
        if not model_path:
            # Registry fallback (persistent across restarts): resolve active model from uploads registry.
            try:
                from app.services.ltr_model_registry import resolve_active_model_paths  # noqa: WPS433

                mp, man_p, spec_v, _mid = resolve_active_model_paths()
                if mp:
                    model_path = str(mp)
                    settings.LTR_MODEL_PATH = str(mp)
                if man_p:
                    settings.LTR_MODEL_MANIFEST_PATH = str(man_p)
                if spec_v:
                    settings.LTR_FEATURE_SPEC_VERSION = int(spec_v)
            except Exception:
                pass

        if not model_path:
            raise ValueError("LTR reranker requires model_path (pass model_path=... or set LTR_MODEL_PATH)")

        manifest_path = str(kwargs.get("manifest_path") or "").strip() or str(getattr(settings, "LTR_MODEL_MANIFEST_PATH", "") or "").strip()

        spec_version = kwargs.get("feature_spec_version")
        if spec_version is None:
            spec_version = getattr(settings, "LTR_FEATURE_SPEC_VERSION", 1)

        feature_names = kwargs.get("feature_names")
        if isinstance(feature_names, (list, tuple)) and feature_names:
            spec = LTRFeatureSpec(
                schema="mimirq.ltr_features.custom",
                feature_names=tuple(str(x) for x in feature_names if x is not None),
            )
        else:
            spec = LTRFeatureSpec.from_version(spec_version)

        cache_key = _local_cache_key(
            "ltr",
            [
                model_path,
                manifest_path,
                getattr(spec, "schema", ""),
                ",".join(getattr(spec, "feature_names", ()) or ()),
            ],
        )
        with _local_reranker_lock:
            cached = _local_reranker_cache.get(cache_key)
            if cached is not None:
                return cached
            inst = LTRReranker(
                model_path=model_path,
                spec=spec,
                manifest_path=(manifest_path or None),
            )
            _local_reranker_cache[cache_key] = inst
            return inst

    # Local cross-encoder reranker (sentence-transformers).
    elif provider in ("cross_encoder", "cross-encoder", "sentence_transformers", "sentence-transformers"):
        from app.rag.reranker.cross_encoder import CrossEncoderReranker

        model_name = model_name or settings.RERANKER_MODEL or "BAAI/bge-reranker-v2-m3"
        device = kwargs.get("device")
        cache_key = _local_cache_key("cross_encoder", [str(model_name or ""), str(device or "")])
        with _local_reranker_lock:
            cached = _local_reranker_cache.get(cache_key)
            if cached is not None:
                return cached
            inst = CrossEncoderReranker(model_name=model_name, device=(str(device) if device is not None else None))
            _local_reranker_cache[cache_key] = inst
            return inst
    
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

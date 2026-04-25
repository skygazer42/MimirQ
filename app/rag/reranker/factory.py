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

DEFAULT_RERANKER_MODEL = "BAAI/bge-reranker-v2-m3"


def describe_reranker_provider(provider: str | None, **kwargs: Any) -> dict[str, Any]:
    normalized = str(provider or "").strip().lower() or "openai"
    provider_name = str(kwargs.get("provider_name") or "").strip().lower() or None

    if normalized in {"none", "off", "false", "0"}:
        return {"provider": "none", "tier": "disabled"}

    if normalized in {"cross_encoder", "cross-encoder", "sentence_transformers", "sentence-transformers"}:
        return {"provider": "cross_encoder", "tier": "prod"}
    if normalized == "long_context":
        return {"provider": "long_context", "tier": "prod"}
    if normalized == "mmr":
        return {"provider": "mmr", "tier": "prod"}
    if normalized in {"local_bge_v2_m3", "bge_v2_m3"}:
        return {"provider": "local_bge_v2_m3", "tier": "prod"}

    if normalized in {"ltr", "xgboost_ltr"}:
        return {"provider": "ltr", "tier": "prod"}

    if normalized in {"weighted", "parent_child", "pc", "kg_pagerank", "kg_rrf"}:
        return {"provider": normalized, "tier": "prod"}

    if normalized in {"llm", "openai", "dashscope", "aliyun"}:
        return {"provider": normalized, "tier": "experimental"}

    if normalized in {"colbert", "late_interaction"}:
        mode = provider_name or str(getattr(settings, "COLBERT_RERANK_PROVIDER", "deterministic") or "deterministic").strip().lower()
        if mode == "deterministic":
            return {"provider": "colbert", "tier": "offline_only", "mode": "deterministic"}
        return {"provider": "colbert", "tier": "experimental", "mode": mode}

    return {"provider": normalized, "tier": "experimental"}


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
        
        model_name = model_name or settings.RERANKER_MODEL or DEFAULT_RERANKER_MODEL
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
        
        model_name = model_name or settings.RERANKER_MODEL or DEFAULT_RERANKER_MODEL
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
        from app.rag.reranker.colbert import (
            ColBERTReranker,
            check_colbert_provider_readiness,
            warmup_colbert_embedder,
        )

        embedder = kwargs.get("embedder")
        provider_name = str(
            kwargs.get("provider_name")
            or getattr(settings, "COLBERT_RERANK_PROVIDER", "deterministic")
            or "deterministic"
        ).strip().lower()
        if provider_name not in {"deterministic", "hf"}:
            provider_name = "deterministic"
        resolved_model_name = str(
            kwargs.get("colbert_model_name")
            or model_name
            or getattr(settings, "COLBERT_RERANK_MODEL_NAME", "")
            or ""
        ).strip()
        device = str(kwargs.get("device") or getattr(settings, "COLBERT_RERANK_DEVICE", "cpu") or "cpu").strip() or "cpu"
        batch_size = max(1, int(kwargs.get("batch_size") or getattr(settings, "COLBERT_RERANK_BATCH_SIZE", 16) or 16))
        max_length = max(8, int(kwargs.get("max_length") or getattr(settings, "COLBERT_RERANK_MAX_LENGTH", 256) or 256))
        deterministic_dim = max(
            2,
            int(kwargs.get("deterministic_dim") or getattr(settings, "COLBERT_RERANK_EMBED_DIM", 64) or 64),
        )
        strict_healthcheck = bool(
            kwargs.get("healthcheck_strict")
            if kwargs.get("healthcheck_strict") is not None
            else getattr(settings, "COLBERT_RERANK_HEALTHCHECK_STRICT", False)
        )
        warmup_enabled = bool(
            kwargs.get("warmup_enabled")
            if kwargs.get("warmup_enabled") is not None
            else getattr(settings, "COLBERT_RERANK_WARMUP_ENABLED", False)
        )

        provider_health = check_colbert_provider_readiness(
            provider_name=provider_name,
            model_name=resolved_model_name,
            device=device,
        )
        warmup_status: dict[str, Any] = {}
        effective_provider_name = provider_name
        if provider_name == "hf" and not bool(provider_health.get("ready")):
            if strict_healthcheck:
                raise ValueError(
                    f"colbert_provider_unready:{str(provider_health.get('reason') or 'unknown')}"
                )
            effective_provider_name = "deterministic"
            provider_health = {
                **dict(provider_health or {}),
                "ready": False,
                "reason": str(provider_health.get("reason") or "unready"),
                "downgraded_to": "deterministic",
            }

        if warmup_enabled and effective_provider_name == "hf":
            warmup_status = warmup_colbert_embedder(
                provider_name=effective_provider_name,
                model_name=resolved_model_name,
                device=device,
                batch_size=batch_size,
                max_length=max_length,
                deterministic_dim=deterministic_dim,
            )
            if not bool(warmup_status.get("ok")):
                if strict_healthcheck:
                    raise ValueError(
                        f"colbert_provider_unready:{str(warmup_status.get('reason') or 'warmup_failed')}"
                    )
                effective_provider_name = "deterministic"
                provider_health = {
                    **dict(provider_health or {}),
                    "ready": False,
                    "reason": str(warmup_status.get("reason") or "warmup_failed"),
                    "downgraded_to": "deterministic",
                }

        if embedder is not None:
            return ColBERTReranker(
                provider_name=effective_provider_name,
                model_name=resolved_model_name,
                device=device,
                batch_size=batch_size,
                max_length=max_length,
                deterministic_dim=deterministic_dim,
                embedder=embedder,
                provider_health=provider_health,
                warmup_status=warmup_status,
            )

        cache_key = _local_cache_key(
            "colbert",
            [
                # Include the requested provider so a deterministic instance created as a
                # fallback (hf -> deterministic) does not get merged with a "native"
                # deterministic instance in the cache (the provider_health differs).
                provider_name,
                effective_provider_name,
                resolved_model_name,
                device,
                str(batch_size),
                str(max_length),
                str(deterministic_dim),
                str(bool(warmup_enabled)),
            ],
        )
        with _local_reranker_lock:
            cached = _local_reranker_cache.get(cache_key)
            if cached is not None:
                return cached
            inst = ColBERTReranker(
                provider_name=effective_provider_name,
                model_name=resolved_model_name,
                device=device,
                batch_size=batch_size,
                max_length=max_length,
                deterministic_dim=deterministic_dim,
                provider_health=provider_health,
                warmup_status=warmup_status,
            )
            _local_reranker_cache[cache_key] = inst
            return inst

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

        model_name = model_name or settings.RERANKER_MODEL or DEFAULT_RERANKER_MODEL
        device = kwargs.get("device")
        cache_key = _local_cache_key("cross_encoder", [str(model_name or ""), str(device or "")])
        with _local_reranker_lock:
            cached = _local_reranker_cache.get(cache_key)
            if cached is not None:
                return cached
            inst = CrossEncoderReranker(model_name=model_name, device=(str(device) if device is not None else None))
            _local_reranker_cache[cache_key] = inst
            return inst

    elif provider == "long_context":
        from app.rag.reranker.long_context_rerank import LongContextReranker

        scorer = kwargs.get("scorer")
        if scorer is not None:
            return LongContextReranker(scorer=scorer, model_name=model_name)

        resolved_model = str(model_name or "long_context:deterministic").strip() or "long_context:deterministic"
        cache_key = _local_cache_key("long_context", [resolved_model])
        with _local_reranker_lock:
            cached = _local_reranker_cache.get(cache_key)
            if cached is not None:
                return cached
            inst = LongContextReranker(model_name=resolved_model)
            _local_reranker_cache[cache_key] = inst
            return inst

    elif provider == "mmr":
        from app.rag.reranker.mmr import MMRReranker

        lambda_mult = float(kwargs.get("lambda_mult") or kwargs.get("mmr_lambda") or settings.RETRIEVAL_MMR_LAMBDA or 0.7)
        cache_key = _local_cache_key("mmr", [str(round(lambda_mult, 6))])
        with _local_reranker_lock:
            cached = _local_reranker_cache.get(cache_key)
            if cached is not None:
                return cached
            inst = MMRReranker(lambda_mult=lambda_mult)
            _local_reranker_cache[cache_key] = inst
            return inst

    elif provider in ("local_bge_v2_m3", "bge_v2_m3"):
        from app.rag.reranker.local_bge_v2_m3 import LocalBGEV2M3Reranker

        device = kwargs.get("device")
        cache_key = _local_cache_key("local_bge_v2_m3", [str(model_name or ""), str(device or "")])
        with _local_reranker_lock:
            cached = _local_reranker_cache.get(cache_key)
            if cached is not None:
                return cached
            inst = LocalBGEV2M3Reranker(model_name=model_name, device=(str(device) if device is not None else None))
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
        
        model_name = model_name or settings.RERANKER_MODEL or DEFAULT_RERANKER_MODEL
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

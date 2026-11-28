"""
Reranker factory functions.

Provide a unified reranker creation interface.
"""

import hashlib
import json
import logging
import threading
from collections.abc import Callable
from importlib import import_module
from typing import Any

from app.infrastructure.config import settings
from app.rag.retrieval.reranking.base import BaseReranker
from app.rag.retrieval.reranking.providers import get_reranker_provider_family
from app.rag.retrieval.reranking.types import RerankCandidate, RerankResult, SyncReranker

logger = logging.getLogger("app.rag.reranker.factory")

_api_reranker_lock = threading.Lock()
_api_reranker_cache: dict[str, BaseReranker] = {}
_local_reranker_lock = threading.Lock()
_local_reranker_cache: dict[str, BaseReranker] = {}


def _api_cache_key(
    provider: str,
    *,
    model: str,
    base_url: str,
    api_key: str,
    timeout: float,
    init_kwargs: dict[str, Any],
) -> str:
    payload = json.dumps(
        {
            "api_key": api_key,
            "base_url": base_url,
            "init_kwargs": init_kwargs,
            "model": model,
            "timeout": timeout,
        },
        sort_keys=True,
        separators=(",", ":"),
        default=repr,
    )
    digest = hashlib.sha256(payload.encode("utf-8", errors="ignore")).hexdigest()
    return f"{provider}:{digest}"


def _local_cache_key(provider: str, parts: list[str]) -> str:
    payload = "|".join([provider.lower().strip(), *parts])
    digest = hashlib.sha256(payload.encode("utf-8", errors="ignore")).hexdigest()[:16]
    return f"{provider}:{digest}"


def _load_attr(module_name: str, attr_name: str) -> Any:
    return getattr(import_module(module_name), attr_name)


def _get_or_create_cached_reranker(
    *,
    cache: dict[str, BaseReranker],
    lock: threading.Lock,
    cache_key: str,
    build: Callable[[], BaseReranker],
) -> BaseReranker:
    with lock:
        cached = cache.get(cache_key)
        if cached is not None:
            return cached
        inst = build()
        cache[cache_key] = inst
        return inst


def _build_dashscope_reranker(
    requested_provider: str,
    *,
    model_name: str | None,
    api_key: str | None,
    base_url: str | None,
    **kwargs: Any,
) -> BaseReranker:
    dashscope_reranker_cls = _load_attr("app.rag.retrieval.reranking.api", "DashScopeReranker")

    resolved_model_name = settings.RERANKER_MODEL if model_name is None else model_name
    resolved_api_key = api_key
    if api_key is None:
        configured_key = settings.RERANKER_API_KEY
        resolved_api_key = settings.LLM_API_KEY if configured_key == "" else configured_key
    resolved_base_url = (
        "https://dashscope.aliyuncs.com/api/v1/services/rerank" if base_url is None else base_url.strip()
    )

    timeout = float(settings.RERANKER_API_TIMEOUT_SEC if kwargs.get("timeout") is None else kwargs["timeout"])
    kwargs_copy = {k: v for k, v in kwargs.items() if k != "timeout"}
    cache_key = _api_cache_key(
        requested_provider,
        model=resolved_model_name,
        base_url=resolved_base_url,
        api_key=resolved_api_key,
        timeout=timeout,
        init_kwargs=kwargs_copy,
    )
    return _get_or_create_cached_reranker(
        cache=_api_reranker_cache,
        lock=_api_reranker_lock,
        cache_key=cache_key,
        build=lambda: dashscope_reranker_cls(
            model_name=resolved_model_name,
            api_key=resolved_api_key,
            base_url=resolved_base_url,
            timeout=timeout,
            **kwargs_copy,
        ),
    )


def _build_openai_reranker(
    requested_provider: str,
    *,
    model_name: str | None,
    api_key: str | None,
    base_url: str | None,
    **kwargs: Any,
) -> BaseReranker:
    openai_reranker_cls = _load_attr("app.rag.retrieval.reranking.api", "OpenAIReranker")

    resolved_model_name = settings.RERANKER_MODEL if model_name is None else model_name
    resolved_api_key = api_key
    if api_key is None:
        configured_key = settings.RERANKER_API_KEY
        resolved_api_key = settings.LLM_API_KEY if configured_key == "" else configured_key
    resolved_base_url = base_url
    if base_url is None:
        configured_base = settings.RERANKER_API_BASE
        resolved_base_url = settings.LLM_API_BASE if configured_base == "" else configured_base
    timeout = float(settings.RERANKER_API_TIMEOUT_SEC if kwargs.get("timeout") is None else kwargs["timeout"])
    kwargs_copy = {k: v for k, v in kwargs.items() if k != "timeout"}
    cache_key = _api_cache_key(
        requested_provider,
        model=resolved_model_name,
        base_url=resolved_base_url,
        api_key=resolved_api_key,
        timeout=timeout,
        init_kwargs=kwargs_copy,
    )
    return _get_or_create_cached_reranker(
        cache=_api_reranker_cache,
        lock=_api_reranker_lock,
        cache_key=cache_key,
        build=lambda: openai_reranker_cls(
            model_name=resolved_model_name,
            api_key=resolved_api_key,
            base_url=resolved_base_url,
            timeout=timeout,
            **kwargs_copy,
        ),
    )


def _build_llm_reranker(_requested_provider: str, **_kwargs: Any) -> BaseReranker:
    get_llm_reranker = _load_attr("app.rag.retrieval.reranking.llm", "get_llm_reranker")
    return get_llm_reranker()


def _build_parent_child_reranker(_requested_provider: str, **_kwargs: Any) -> BaseReranker:
    parent_child_reranker_cls = _load_attr("app.rag.retrieval.reranking.parent_child", "ParentChildReranker")
    return parent_child_reranker_cls()


def _build_weighted_reranker(_requested_provider: str, **kwargs: Any) -> BaseReranker:
    weighted_reranker_cls = _load_attr("app.rag.retrieval.reranking.weighted", "WeightedReranker")

    weights = kwargs.get("weights")
    if not weights:
        raise ValueError("WeightedReranker requires 'weights' parameter")

    tenant_id = kwargs["tenant_id"]
    embedding_fn = kwargs.get("embedding_fn")
    return weighted_reranker_cls(
        tenant_id=tenant_id,
        weights=weights,
        embedding_fn=embedding_fn,
    )


def _build_long_context_reranker(
    _requested_provider: str,
    *,
    model_name: str | None,
    **kwargs: Any,
) -> BaseReranker:
    long_context_reranker_cls = _load_attr("app.rag.retrieval.reranking.long_context", "LongContextReranker")

    scorer = kwargs.get("scorer")
    if scorer is not None:
        return long_context_reranker_cls(scorer=scorer, model_name=model_name)

    candidate = long_context_reranker_cls(model_name=model_name)
    cache_key = _local_cache_key("long_context", [candidate.model_name])
    return _get_or_create_cached_reranker(
        cache=_local_reranker_cache,
        lock=_local_reranker_lock,
        cache_key=cache_key,
        build=lambda: candidate,
    )


def _build_mmr_reranker(_requested_provider: str, **kwargs: Any) -> BaseReranker:
    mmr_reranker_cls = _load_attr("app.rag.retrieval.reranking.mmr", "MMRReranker")

    requested_lambda = kwargs.get("lambda_mult")
    if requested_lambda is None:
        requested_lambda = kwargs.get("mmr_lambda")
    lambda_mult = float(settings.RETRIEVAL_MMR_LAMBDA if requested_lambda is None else requested_lambda)
    cache_key = _local_cache_key("mmr", [str(round(lambda_mult, 6))])
    return _get_or_create_cached_reranker(
        cache=_local_reranker_cache,
        lock=_local_reranker_lock,
        cache_key=cache_key,
        build=lambda: mmr_reranker_cls(lambda_mult=lambda_mult),
    )


def _build_kg_reranker(*, provider: str, **_kwargs: Any) -> BaseReranker:
    from app.rag.kg.search.config import RerankStrategy

    kg_reranker_cls = _load_attr("app.rag.retrieval.reranking.kg", "KGReranker")
    strategy = RerankStrategy.PAGERANK if provider == "kg_pagerank" else RerankStrategy.RRF
    return kg_reranker_cls(strategy)


_PROVIDER_BUILDERS = {
    "dashscope": _build_dashscope_reranker,
    "openai": _build_openai_reranker,
    "llm": _build_llm_reranker,
    "parent_child": _build_parent_child_reranker,
    "weighted": _build_weighted_reranker,
    "long_context": _build_long_context_reranker,
    "mmr": _build_mmr_reranker,
    "kg_pagerank": _build_kg_reranker,
    "kg_rrf": _build_kg_reranker,
}


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
    requested_provider = provider.lower()
    from app.infrastructure.model_policy import reject_retired_provider

    reject_retired_provider(requested_provider, capability="reranker")
    family = get_reranker_provider_family(requested_provider)
    dispatch_key = family.canonical_name if family is not None else requested_provider
    builder = _PROVIDER_BUILDERS.get(dispatch_key)
    if builder is None:
        raise ValueError(f"Unknown reranker provider: {requested_provider!r}")
    if dispatch_key == "kg_pagerank" or dispatch_key == "kg_rrf":
        return builder(provider=dispatch_key, model_name=model_name, api_key=api_key, base_url=base_url, **kwargs)
    return builder(
        requested_provider,
        model_name=model_name,
        api_key=api_key,
        base_url=base_url,
        **kwargs,
    )


class _IdentityReranker:
    """Keep retrieval order when reranking is explicitly disabled."""

    def __init__(self, provider: str | None = None) -> None:
        self.provider = str(provider or "none").strip().lower() or "none"
        self.model_name = None

    def rerank(self, query: str, candidates: list[RerankCandidate], **kwargs: Any) -> RerankResult:
        del query, kwargs
        ordered_ids: list[str] = []
        score_map: dict[str, float] = {}
        for candidate in candidates:
            candidate_id = candidate.id.strip()
            if not candidate_id:
                continue
            ordered_ids.append(candidate_id)
            raw_score = candidate.metadata.get("score")
            if raw_score is None:
                raw_score = candidate.metadata.get("retrieval_score", 0.0)
            try:
                score_map[candidate_id] = float(raw_score)
            except (OverflowError, TypeError, ValueError):
                score_map[candidate_id] = 0.0
        return RerankResult(
            ordered_ids=ordered_ids,
            score_map=score_map,
            items=[],
            clues=[],
            stats={"fallback": "identity"},
            elapsed_sec=0.0,
            model_used=None,
            provider=self.provider,
        )


def get_reranker_for_retrieval(provider: str | None = None, **kwargs: Any) -> SyncReranker:
    """Resolve an optional retrieval reranker without a second factory module."""
    family = get_reranker_provider_family(provider)
    if not provider or not provider.strip() or (family and family.canonical_name == "none"):
        return _IdentityReranker(provider)
    return get_reranker(provider, **kwargs)


def reset_reranker_caches() -> None:
    """Forget process models after request draining and before the HTTP pool closes.

    API sessions belong to individual scoring calls. Clearing these caches does
    not close a session or invalidate a model already held by an active caller.
    """
    with _api_reranker_lock:
        _api_reranker_cache.clear()
    with _local_reranker_lock:
        _local_reranker_cache.clear()
    from app.rag.retrieval.reranking.llm import reset_llm_reranker

    reset_llm_reranker()

"""
Reranker factory functions.

Provide a unified reranker creation interface.
"""

import hashlib
import json
import threading
from importlib import import_module
from typing import Any

from app.core.config import settings
from app.rag.core.logging import get_logger
from app.rag.reranker.base import BaseReranker
from app.rag.reranker.capabilities import describe_reranker_provider as describe_reranker_provider
from app.rag.reranker.registry import get_reranker_provider_family

logger = get_logger(__name__)

_api_reranker_lock = threading.Lock()
_api_reranker_cache: dict[str, BaseReranker] = {}
_local_reranker_lock = threading.Lock()
_local_reranker_cache: dict[str, BaseReranker] = {}

DEFAULT_RERANKER_MODEL = "BAAI/bge-reranker-v2-m3"


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
    payload = "|".join([str(provider or "").lower().strip()] + [str(p or "") for p in (parts or [])])
    digest = hashlib.sha256(payload.encode("utf-8", errors="ignore")).hexdigest()[:16]
    return f"{provider}:{digest}"


def _load_attr(module_name: str, attr_name: str) -> Any:
    return getattr(import_module(module_name), attr_name)


def _get_or_create_cached_reranker(
    *,
    cache: dict[str, BaseReranker],
    lock: threading.Lock,
    cache_key: str,
    build: Any,
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
    dashscope_reranker_cls = _load_attr("app.rag.reranker.dashscope", "DashScopeReranker")

    resolved_model_name = model_name or settings.RERANKER_MODEL or DEFAULT_RERANKER_MODEL
    resolved_api_key = api_key or settings.RERANKER_API_KEY or settings.LLM_API_KEY
    resolved_base_url = base_url or "https://dashscope.aliyuncs.com/api/v1/services/rerank"

    timeout = float(kwargs.get("timeout") or settings.RERANKER_API_TIMEOUT_SEC or 30.0)
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
    openai_reranker_cls = _load_attr("app.rag.reranker.openai", "OpenAIReranker")

    resolved_model_name = model_name or settings.RERANKER_MODEL or DEFAULT_RERANKER_MODEL
    resolved_api_key = api_key or settings.RERANKER_API_KEY or settings.LLM_API_KEY
    resolved_base_url = base_url or settings.RERANKER_API_BASE or settings.LLM_API_BASE

    timeout = float(kwargs.get("timeout") or settings.RERANKER_API_TIMEOUT_SEC or 30.0)
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
    get_llm_reranker = _load_attr("app.rag.reranker.llm_based", "get_llm_reranker")
    return get_llm_reranker()


def _build_parent_child_reranker(_requested_provider: str, **_kwargs: Any) -> BaseReranker:
    parent_child_reranker_cls = _load_attr("app.rag.reranker.parent_child", "ParentChildReranker")
    return parent_child_reranker_cls()


def _build_weighted_reranker(_requested_provider: str, **kwargs: Any) -> BaseReranker:
    weighted_reranker_cls = _load_attr("app.rag.reranker.hybrid", "WeightedReranker")

    weights = kwargs.get("weights")
    if not weights:
        raise ValueError("WeightedReranker requires 'weights' parameter")

    tenant_id = kwargs.get("tenant_id", "")
    embedding_fn = kwargs.get("embedding_fn")
    return weighted_reranker_cls(
        tenant_id=tenant_id,
        weights=weights,
        embedding_fn=embedding_fn,
    )


def _build_colbert_reranker(
    _requested_provider: str,
    *,
    model_name: str | None,
    **kwargs: Any,
) -> BaseReranker:
    colbert_reranker_cls = _load_attr("app.rag.reranker.colbert", "ColBERTReranker")
    check_colbert_provider_readiness = _load_attr("app.rag.reranker.colbert", "check_colbert_provider_readiness")
    warmup_colbert_embedder = _load_attr("app.rag.reranker.colbert", "warmup_colbert_embedder")

    embedder = kwargs.get("embedder")
    provider_name = (
        str(
            kwargs.get("provider_name")
            or getattr(settings, "COLBERT_RERANK_PROVIDER", "deterministic")
            or "deterministic"
        )
        .strip()
        .lower()
    )
    if provider_name not in {"deterministic", "hf"}:
        provider_name = "deterministic"
    resolved_model_name = str(
        kwargs.get("colbert_model_name") or model_name or getattr(settings, "COLBERT_RERANK_MODEL_NAME", "") or ""
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
            raise ValueError(f"colbert_provider_unready:{str(provider_health.get('reason') or 'unknown')}")
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
                raise ValueError(f"colbert_provider_unready:{str(warmup_status.get('reason') or 'warmup_failed')}")
            effective_provider_name = "deterministic"
            provider_health = {
                **dict(provider_health or {}),
                "ready": False,
                "reason": str(warmup_status.get("reason") or "warmup_failed"),
                "downgraded_to": "deterministic",
            }

    if embedder is not None:
        return colbert_reranker_cls(
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
    return _get_or_create_cached_reranker(
        cache=_local_reranker_cache,
        lock=_local_reranker_lock,
        cache_key=cache_key,
        build=lambda: colbert_reranker_cls(
            provider_name=effective_provider_name,
            model_name=resolved_model_name,
            device=device,
            batch_size=batch_size,
            max_length=max_length,
            deterministic_dim=deterministic_dim,
            provider_health=provider_health,
            warmup_status=warmup_status,
        ),
    )


def _build_ltr_reranker(_requested_provider: str, **kwargs: Any) -> BaseReranker:
    ltr_feature_spec_cls = _load_attr("app.rag.reranker.ltr", "LTRFeatureSpec")
    ltr_reranker_cls = _load_attr("app.rag.reranker.ltr", "LTRReranker")

    model_path = (
        str(kwargs.get("model_path") or "").strip() or str(getattr(settings, "LTR_MODEL_PATH", "") or "").strip()
    )
    if not model_path:
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
        except Exception as exc:
            logger.debug("Ignoring LTR active model registry lookup failure: %s", exc)

    if not model_path:
        raise ValueError("LTR reranker requires model_path (pass model_path=... or set LTR_MODEL_PATH)")

    manifest_path = (
        str(kwargs.get("manifest_path") or "").strip()
        or str(getattr(settings, "LTR_MODEL_MANIFEST_PATH", "") or "").strip()
    )

    spec_version = kwargs.get("feature_spec_version")
    if spec_version is None:
        spec_version = getattr(settings, "LTR_FEATURE_SPEC_VERSION", 1)

    feature_names = kwargs.get("feature_names")
    if isinstance(feature_names, (list, tuple)) and feature_names:
        spec = ltr_feature_spec_cls(
            schema="mimirq.ltr_features.custom",
            feature_names=tuple(str(x) for x in feature_names if x is not None),
        )
    else:
        spec = ltr_feature_spec_cls.from_version(spec_version)

    cache_key = _local_cache_key(
        "ltr",
        [
            model_path,
            manifest_path,
            getattr(spec, "schema", ""),
            ",".join(getattr(spec, "feature_names", ()) or ()),
        ],
    )
    return _get_or_create_cached_reranker(
        cache=_local_reranker_cache,
        lock=_local_reranker_lock,
        cache_key=cache_key,
        build=lambda: ltr_reranker_cls(
            model_path=model_path,
            spec=spec,
            manifest_path=(manifest_path or None),
        ),
    )


def _build_cross_encoder_reranker(
    _requested_provider: str,
    *,
    model_name: str | None,
    **kwargs: Any,
) -> BaseReranker:
    cross_encoder_reranker_cls = _load_attr("app.rag.reranker.cross_encoder", "CrossEncoderReranker")

    resolved_model_name = model_name or settings.RERANKER_MODEL or DEFAULT_RERANKER_MODEL
    device = kwargs.get("device")
    cache_key = _local_cache_key("cross_encoder", [str(resolved_model_name or ""), str(device or "")])
    return _get_or_create_cached_reranker(
        cache=_local_reranker_cache,
        lock=_local_reranker_lock,
        cache_key=cache_key,
        build=lambda: cross_encoder_reranker_cls(
            model_name=resolved_model_name,
            device=(str(device) if device is not None else None),
        ),
    )


def _build_long_context_reranker(
    _requested_provider: str,
    *,
    model_name: str | None,
    **kwargs: Any,
) -> BaseReranker:
    long_context_reranker_cls = _load_attr("app.rag.reranker.long_context_rerank", "LongContextReranker")

    scorer = kwargs.get("scorer")
    if scorer is not None:
        return long_context_reranker_cls(scorer=scorer, model_name=model_name)

    resolved_model = str(model_name or "long_context:deterministic").strip() or "long_context:deterministic"
    cache_key = _local_cache_key("long_context", [resolved_model])
    return _get_or_create_cached_reranker(
        cache=_local_reranker_cache,
        lock=_local_reranker_lock,
        cache_key=cache_key,
        build=lambda: long_context_reranker_cls(model_name=resolved_model),
    )


def _build_mmr_reranker(_requested_provider: str, **kwargs: Any) -> BaseReranker:
    mmr_reranker_cls = _load_attr("app.rag.reranker.mmr", "MMRReranker")

    lambda_mult = float(kwargs.get("lambda_mult") or kwargs.get("mmr_lambda") or settings.RETRIEVAL_MMR_LAMBDA or 0.7)
    cache_key = _local_cache_key("mmr", [str(round(lambda_mult, 6))])
    return _get_or_create_cached_reranker(
        cache=_local_reranker_cache,
        lock=_local_reranker_lock,
        cache_key=cache_key,
        build=lambda: mmr_reranker_cls(lambda_mult=lambda_mult),
    )


def _build_local_bge_v2_m3_reranker(
    _requested_provider: str,
    *,
    model_name: str | None,
    **kwargs: Any,
) -> BaseReranker:
    local_bge_v2_m3_reranker_cls = _load_attr("app.rag.reranker.local_bge_v2_m3", "LocalBGEV2M3Reranker")

    device = kwargs.get("device")
    cache_key = _local_cache_key("local_bge_v2_m3", [str(model_name or ""), str(device or "")])
    return _get_or_create_cached_reranker(
        cache=_local_reranker_cache,
        lock=_local_reranker_lock,
        cache_key=cache_key,
        build=lambda: local_bge_v2_m3_reranker_cls(
            model_name=model_name,
            device=(str(device) if device is not None else None),
        ),
    )


def _build_kg_reranker(*, provider: str, **_kwargs: Any) -> BaseReranker:
    from app.rag.kg.search.config import RerankStrategy

    kg_reranker_cls = _load_attr("app.rag.reranker.kg", "KGReranker")
    strategy = RerankStrategy.PAGERANK if provider == "kg_pagerank" else RerankStrategy.RRF
    return kg_reranker_cls(strategy)


_PROVIDER_BUILDERS = {
    "dashscope": _build_dashscope_reranker,
    "openai": _build_openai_reranker,
    "llm": _build_llm_reranker,
    "parent_child": _build_parent_child_reranker,
    "weighted": _build_weighted_reranker,
    "colbert": _build_colbert_reranker,
    "ltr": _build_ltr_reranker,
    "cross_encoder": _build_cross_encoder_reranker,
    "long_context": _build_long_context_reranker,
    "mmr": _build_mmr_reranker,
    "local_bge_v2_m3": _build_local_bge_v2_m3_reranker,
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
    requested_provider = (provider or "").lower()
    family = get_reranker_provider_family(requested_provider)
    dispatch_key = family.canonical_name if family is not None else requested_provider
    builder = _PROVIDER_BUILDERS.get(dispatch_key)
    if builder is None:
        raise ValueError(f"Unknown reranker provider: {requested_provider!r}")
    if dispatch_key == "kg_pagerank" or dispatch_key == "kg_rrf":
        return builder(provider=requested_provider, model_name=model_name, api_key=api_key, base_url=base_url, **kwargs)
    return builder(
        requested_provider,
        model_name=model_name,
        api_key=api_key,
        base_url=base_url,
        **kwargs,
    )


# Backward compatibility: legacy factory function (kept for a while).
def get_rag_reranker(provider: str | None = None) -> BaseReranker:
    """
    Get the RAG reranker (legacy interface, deprecated).

    Use get_reranker() instead.
    """
    import warnings

    warnings.warn("get_rag_reranker() is deprecated, use get_reranker() instead", DeprecationWarning, stacklevel=2)

    provider = (provider or "llm").lower()
    if provider == "pc":
        return get_reranker("parent_child")
    else:
        return get_reranker("llm")

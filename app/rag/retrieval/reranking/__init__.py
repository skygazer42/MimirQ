"""
Reranker module.

Exports are resolved lazily so callers can import a specific reranker submodule
without pulling in every provider implementation and its optional dependencies.
"""

from importlib import import_module
from typing import Any

_MODULE_BASE = "app.rag.retrieval.reranking.base"
_MODULE_HYBRID = "app.rag.retrieval.reranking.weighted"
_MODULE_LLM_BASED = "app.rag.retrieval.reranking.llm"

_EXPORTS: dict[str, tuple[str, str]] = {
    "BaseReranker": (_MODULE_BASE, "BaseReranker"),
    "APIReranker": (_MODULE_BASE, "APIReranker"),
    "DocumentReranker": (_MODULE_BASE, "DocumentReranker"),
    "OpenAIReranker": ("app.rag.retrieval.reranking.api", "OpenAIReranker"),
    "DashScopeReranker": ("app.rag.retrieval.reranking.api", "DashScopeReranker"),
    "WeightedReranker": (_MODULE_HYBRID, "WeightedReranker"),
    "ParentChildReranker": ("app.rag.retrieval.reranking.parent_child", "ParentChildReranker"),
    "LLMReranker": (_MODULE_LLM_BASED, "LLMReranker"),
    "KGReranker": ("app.rag.retrieval.reranking.kg", "KGReranker"),
    "get_kg_reranker": ("app.rag.retrieval.reranking.kg", "get_kg_reranker"),
    "RerankCandidate": ("app.rag.retrieval.reranking.types", "RerankCandidate"),
    "RerankResult": ("app.rag.retrieval.reranking.types", "RerankResult"),
    "LLMRerankResult": (_MODULE_LLM_BASED, "LLMRerankResult"),
    "Weights": (_MODULE_HYBRID, "Weights"),
    "VectorSetting": (_MODULE_HYBRID, "VectorSetting"),
    "KeywordSetting": (_MODULE_HYBRID, "KeywordSetting"),
    "RerankMode": (_MODULE_HYBRID, "RerankMode"),
    "get_reranker": ("app.rag.retrieval.reranking.factory", "get_reranker"),
    "describe_reranker_provider": ("app.rag.retrieval.reranking.providers", "describe_reranker_provider"),
    "get_reranker_capabilities": ("app.rag.retrieval.reranking.providers", "get_reranker_capabilities"),
    "list_reranker_capabilities": ("app.rag.retrieval.reranking.providers", "list_reranker_capabilities"),
    "get_reranker_provider_family": ("app.rag.retrieval.reranking.providers", "get_reranker_provider_family"),
    "list_registered_reranker_providers": (
        "app.rag.retrieval.reranking.providers",
        "list_registered_reranker_providers",
    ),
    "get_llm_reranker": (_MODULE_LLM_BASED, "get_llm_reranker"),
}


def __getattr__(name: str) -> Any:
    target = _EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attr_name = target
    value = getattr(import_module(module_name), attr_name)
    globals()[name] = value
    return value


__all__ = list(_EXPORTS)

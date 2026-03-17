"""
Reranker module.

Exports are resolved lazily so callers can import a specific reranker submodule
without pulling in every provider implementation and its optional dependencies.
"""

from __future__ import annotations

from importlib import import_module

_EXPORTS: dict[str, tuple[str, str]] = {
    "BaseReranker": ("app.rag.reranker.base", "BaseReranker"),
    "APIReranker": ("app.rag.reranker.base", "APIReranker"),
    "DocumentReranker": ("app.rag.reranker.base", "DocumentReranker"),
    "OpenAIReranker": ("app.rag.reranker.openai", "OpenAIReranker"),
    "DashScopeReranker": ("app.rag.reranker.dashscope", "DashScopeReranker"),
    "WeightedReranker": ("app.rag.reranker.hybrid", "WeightedReranker"),
    "ParentChildReranker": ("app.rag.reranker.parent_child", "ParentChildReranker"),
    "LLMReranker": ("app.rag.reranker.llm_based", "LLMReranker"),
    "KGReranker": ("app.rag.reranker.kg", "KGReranker"),
    "get_kg_reranker": ("app.rag.reranker.kg", "get_kg_reranker"),
    "RerankCandidate": ("app.rag.reranker.types", "RerankCandidate"),
    "RerankResult": ("app.rag.reranker.types", "RerankResult"),
    "LLMRerankResult": ("app.rag.reranker.llm_based", "LLMRerankResult"),
    "Weights": ("app.rag.reranker.hybrid", "Weights"),
    "VectorSetting": ("app.rag.reranker.hybrid", "VectorSetting"),
    "KeywordSetting": ("app.rag.reranker.hybrid", "KeywordSetting"),
    "RerankMode": ("app.rag.reranker.hybrid", "RerankMode"),
    "get_reranker": ("app.rag.reranker.factory", "get_reranker"),
    "get_rag_reranker": ("app.rag.reranker.factory", "get_rag_reranker"),
    "get_llm_reranker": ("app.rag.reranker.llm_based", "get_llm_reranker"),
}


def __getattr__(name: str):
    target = _EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attr_name = target
    value = getattr(import_module(module_name), attr_name)
    globals()[name] = value
    return value


__all__ = list(_EXPORTS)

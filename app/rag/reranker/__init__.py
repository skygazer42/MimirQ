"""
Reranker module.

Exports are resolved lazily so callers can import a specific reranker submodule
without pulling in every provider implementation and its optional dependencies.
"""


from importlib import import_module

_MODULE_BASE = "app.rag.reranker.base"
_MODULE_HYBRID = "app.rag.reranker.hybrid"
_MODULE_LLM_BASED = "app.rag.reranker.llm_based"

_EXPORTS: dict[str, tuple[str, str]] = {
    "BaseReranker": (_MODULE_BASE, "BaseReranker"),
    "APIReranker": (_MODULE_BASE, "APIReranker"),
    "DocumentReranker": (_MODULE_BASE, "DocumentReranker"),
    "OpenAIReranker": ("app.rag.reranker.openai", "OpenAIReranker"),
    "DashScopeReranker": ("app.rag.reranker.dashscope", "DashScopeReranker"),
    "WeightedReranker": (_MODULE_HYBRID, "WeightedReranker"),
    "ParentChildReranker": ("app.rag.reranker.parent_child", "ParentChildReranker"),
    "LLMReranker": (_MODULE_LLM_BASED, "LLMReranker"),
    "KGReranker": ("app.rag.reranker.kg", "KGReranker"),
    "get_kg_reranker": ("app.rag.reranker.kg", "get_kg_reranker"),
    "RerankCandidate": ("app.rag.reranker.types", "RerankCandidate"),
    "RerankResult": ("app.rag.reranker.types", "RerankResult"),
    "LLMRerankResult": (_MODULE_LLM_BASED, "LLMRerankResult"),
    "Weights": (_MODULE_HYBRID, "Weights"),
    "VectorSetting": (_MODULE_HYBRID, "VectorSetting"),
    "KeywordSetting": (_MODULE_HYBRID, "KeywordSetting"),
    "RerankMode": (_MODULE_HYBRID, "RerankMode"),
    "get_reranker": ("app.rag.reranker.factory", "get_reranker"),
    "get_rag_reranker": ("app.rag.reranker.factory", "get_rag_reranker"),
    "get_llm_reranker": (_MODULE_LLM_BASED, "get_llm_reranker"),
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

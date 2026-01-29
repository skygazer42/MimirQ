"""
Reranker module.

Unified reranker architecture:
- BaseReranker: top-level abstract base class
- APIReranker: HTTP API-based reranker
- DocumentReranker: document-level reranker

API Rerankers:
- OpenAIReranker: OpenAI-style API
- DashScopeReranker: Alibaba Cloud DashScope

Document Rerankers:
- WeightedReranker: hybrid reranking (vector + keyword) [hybrid.py]
- ParentChildReranker: parent/child reranking
- LLMReranker: LLM-based reranking [llm_based.py]
- KGReranker: knowledge graph reranking
"""
from app.rag.reranker.base import APIReranker, BaseReranker, DocumentReranker
from app.rag.reranker.dashscope import DashScopeReranker
from app.rag.reranker.factory import get_rag_reranker, get_reranker
from app.rag.reranker.hybrid import KeywordSetting, RerankMode, VectorSetting, WeightedReranker, Weights
from app.rag.reranker.kg import KGReranker, get_kg_reranker
from app.rag.reranker.llm_based import LLMReranker, LLMRerankResult, get_llm_reranker
from app.rag.reranker.openai import OpenAIReranker
from app.rag.reranker.parent_child import ParentChildReranker
from app.rag.reranker.types import RerankCandidate, RerankResult

__all__ = [
    # Base classes
    "BaseReranker",
    "APIReranker",
    "DocumentReranker",
    
    # API Rerankers
    "OpenAIReranker",
    "DashScopeReranker",
    
    # Document Rerankers
    "WeightedReranker",
    "ParentChildReranker",
    "LLMReranker",
    
    # KG Reranker
    "KGReranker",
    "get_kg_reranker",
    
    # Types
    "RerankCandidate",
    "RerankResult",
    "LLMRerankResult",
    "Weights",
    "VectorSetting",
    "KeywordSetting",
    "RerankMode",
    
    # Factory functions
    "get_reranker",
    "get_rag_reranker",  # Deprecated; kept for backward compatibility.
    "get_llm_reranker",
]


# Backward compatibility: keep old module-level factory functions (defined in factory.py).
# This lets legacy code keep using `from app.rag.reranker import get_reranker`.

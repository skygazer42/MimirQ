"""
Reranker 模块

统一的 Reranker 架构：
- BaseReranker: 顶层抽象基类
- APIReranker: HTTP API 调用型 reranker
- DocumentReranker: 文档级别 reranker
- OpenAIReranker: OpenAI 风格 API
- DashScopeReranker: 阿里云 DashScope
- WeightedReranker: 权重融合重排
- ParentChildReranker: 父子关系重排
- KGReranker: 知识图谱重排

注意：LLMReranker 已移至 app.rag.llm.reranker 模块
"""
from app.rag.reranker.base import BaseReranker, APIReranker, DocumentReranker
from app.rag.reranker.openai import OpenAIReranker
from app.rag.reranker.dashscope import DashScopeReranker
from app.rag.reranker.weighted import WeightedReranker, Weights, VectorSetting, KeywordSetting, RerankMode
from app.rag.reranker.parent_child import ParentChildReranker
from app.rag.reranker.kg import KGReranker, get_kg_reranker
from app.rag.reranker.types import RerankCandidate, RerankResult
from app.rag.reranker.factory import get_reranker, get_rag_reranker
from app.rag.llm.reranker import LLMReranker, get_llm_reranker

__all__ = [
    # 基类
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
    
    # 类型
    "RerankCandidate",
    "RerankResult",
    "Weights",
    "VectorSetting",
    "KeywordSetting",
    "RerankMode",
    
    # 工厂函数
    "get_reranker",
    "get_rag_reranker",  # 已废弃，保留向后兼容
    "get_llm_reranker",
]


# 向后兼容：保留旧的模块级工厂函数（在 factory.py 中已定义）
# 这样旧代码仍然可以使用 from app.rag.reranker import get_reranker

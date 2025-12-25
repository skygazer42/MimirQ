"""
RAG 引擎模块

提供检索增强生成（RAG）核心功能。

主要组件：
- embedding: 向量嵌入模型
- engine: 核心 RAG 引擎
- graph: LangGraph 编排
- agent: Agent 工具
- tools: RAG 工具函数

注意: 为避免循环导入，部分子模块需要直接导入：
- from app.rag.engine import get_rag_engine
- from app.rag.agent import RAGAgent
- from app.rag.tools import search_knowledge_base
"""

# 嵌入模型 (无外部依赖，可以安全导入)
from app.rag.embedding import (
    select_embedding_model,
    test_embedding_model_status,
    DEFAULT_EMBED_MODELS,
)

__all__ = [
    'select_embedding_model',
    'test_embedding_model_status',
    'DEFAULT_EMBED_MODELS',
]


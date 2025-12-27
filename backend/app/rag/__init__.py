"""
RAG 引擎模块

提供检索增强生成（RAG）核心功能。

主要组件：
- chunking: 文档切块（factory, hierarchical, legacy）
- embedding: 向量嵌入模型
- reranker: 重排器（LLM、OpenAI、DashScope、权重融合）
- retriever: 混合检索器（向量 + BM25）
- llm: LLM 抽象层
- kg: 知识图谱（实体/事件抽取、图谱搜索）
- engine: 核心 RAG 引擎
- graph: LangGraph 编排
- agent: Agent 工具
- tools: RAG 工具函数

注意: 为避免循环导入，部分子模块需要直接导入：
- from app.rag.engine import get_rag_engine
- from app.rag.retriever import hybrid_retriever
- from app.rag.chunking import chunker_factory
"""

from app.rag.embedding import (
    select_embedding_model,
    test_embedding_model_status,
    DEFAULT_EMBED_MODELS,
)

__all__ = [
    "select_embedding_model",
    "test_embedding_model_status",
    "DEFAULT_EMBED_MODELS",
]

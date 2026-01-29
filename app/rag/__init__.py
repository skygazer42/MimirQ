"""
RAG Engine Module

Provides core Retrieval-Augmented Generation (RAG) functionality.

Main components:
- chunking: Document chunking (factory, hierarchical, legacy)
- embedding: Vector embedding models
- reranker: Rerankers (LLM, OpenAI, DashScope, weighted fusion)
- retriever: Hybrid retriever (vector + BM25)
- llm: LLM abstraction layer
- kg: Knowledge graph (entity/event extraction, graph search)
- engine: Core RAG engine
- graph: LangGraph orchestration
- agent: Agent tools
- tools: RAG utility functions

Note: To avoid circular imports, some submodules need to be imported directly:
- from app.rag.engine import get_rag_engine
- from app.rag.retriever import hybrid_retriever
- from app.rag.chunking import chunker_factory
"""

from app.rag.embedding import (
    DEFAULT_EMBED_MODELS,
    select_embedding_model,
    test_embedding_model_status,
)

__all__ = [
    "select_embedding_model",
    "test_embedding_model_status",
    "DEFAULT_EMBED_MODELS",
]












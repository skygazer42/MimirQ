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

import importlib
from typing import Any

__all__ = ["select_embedding_model", "probe_embedding_model_status", "DEFAULT_EMBED_MODELS"]


def __getattr__(name: str) -> Any:
    if name == "core":
        # Some tests/monkeypatches resolve dotted paths like "app.rag.core.*" by
        # attribute-walking the package. Provide a lazy import hook so those paths
        # remain stable even when `app.rag` is re-imported in isolation.
        return importlib.import_module("app.rag.core")
    if name == "retriever":
        # Some tests/monkeypatches resolve dotted paths like "app.rag.retriever.*" by
        # attribute-walking the package. Provide a lazy import hook so those paths
        # remain stable even when `app.rag` is re-imported in isolation.
        return importlib.import_module("app.rag.retriever")
    if name == "select_embedding_model":
        from app.rag.embedding import select_embedding_model

        return select_embedding_model
    if name == "probe_embedding_model_status":
        from app.rag.embedding import probe_embedding_model_status

        return probe_embedding_model_status
    if name == "DEFAULT_EMBED_MODELS":
        from app.rag.embedding import DEFAULT_EMBED_MODELS

        return DEFAULT_EMBED_MODELS
    raise AttributeError(name)

"""
Embedding models for vector generation.

This module provides support for multiple embedding backends:
- OpenAI-compatible APIs (SiliconFlow, OpenAI, etc.)
- Ollama local embeddings
- DashScope (Alibaba Cloud)
- Sentence-transformers local models

Usage:
    from app.rag.embedding import select_embedding_model, EmbedModelInfo

    # Get a model instance
    model = select_embedding_model("siliconflow/BAAI/bge-m3")

    # Encode text
    embeddings = model.encode(["Hello world", "Another text"])

    # Async encoding
    embeddings = await model.aencode(["Hello world"])

    # Test connection
    success, message = await model.test_connection()
"""

from app.rag.embedding.adapter import (
    LangChainEmbeddingsAdapter,
    create_langchain_embeddings,
    create_langchain_embeddings_from_config,
)
from app.rag.embedding.base import BaseEmbeddingModel
from app.rag.embedding.config import DEFAULT_EMBED_MODELS, EmbedModelInfo
from app.rag.embedding.factory import select_embedding_model, test_embedding_model_status
from app.rag.embedding.providers import (
    DashScopeEmbedding,
    DeterministicTestEmbedding,
    OllamaEmbedding,
    OpenAICompatibleEmbedding,
    SentenceTransformerEmbedding,
)

__all__ = [
    # Base
    "BaseEmbeddingModel",
    # Providers
    "OpenAICompatibleEmbedding",
    "OllamaEmbedding",
    "SentenceTransformerEmbedding",
    "DashScopeEmbedding",
    "DeterministicTestEmbedding",
    # LangChain adapter
    "LangChainEmbeddingsAdapter",
    "create_langchain_embeddings",
    "create_langchain_embeddings_from_config",
    # Factory
    "select_embedding_model",
    "test_embedding_model_status",
    # Config
    "EmbedModelInfo",
    "DEFAULT_EMBED_MODELS",
]

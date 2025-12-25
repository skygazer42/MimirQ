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

from app.rag.embedding.base import BaseEmbeddingModel
from app.rag.embedding.openai_compatible import OpenAICompatibleEmbedding
from app.rag.embedding.ollama import OllamaEmbedding
from app.rag.embedding.sentence_transformer import SentenceTransformerEmbedding
from app.rag.embedding.dashscope import DashScopeEmbedding
from app.rag.embedding.langchain_adapter import (
    LangChainEmbeddingsAdapter,
    create_langchain_embeddings,
    create_langchain_embeddings_from_config,
)
from app.rag.embedding.factory import select_embedding_model, test_embedding_model_status
from app.rag.embedding.config import EmbedModelInfo, DEFAULT_EMBED_MODELS

__all__ = [
    "BaseEmbeddingModel",
    "OpenAICompatibleEmbedding",
    "OllamaEmbedding",
    "SentenceTransformerEmbedding",
    "DashScopeEmbedding",
    "LangChainEmbeddingsAdapter",
    "create_langchain_embeddings",
    "create_langchain_embeddings_from_config",
    "select_embedding_model",
    "test_embedding_model_status",
    "EmbedModelInfo",
    "DEFAULT_EMBED_MODELS",
]

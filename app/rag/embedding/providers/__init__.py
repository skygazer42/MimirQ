"""
Embedding providers.

Available providers:
- openai: OpenAI-compatible APIs (OpenAI, SiliconFlow, vLLM, etc.)
- ollama: Ollama local embeddings
- dashscope: Alibaba Cloud DashScope
- deterministic_test: Dependency-free lexical vectors for offline integration tests
"""

from app.rag.embedding.providers.dashscope import DashScopeEmbedding
from app.rag.embedding.providers.deterministic_test import DeterministicTestEmbedding
from app.rag.embedding.providers.ollama import OllamaEmbedding
from app.rag.embedding.providers.openai import OpenAICompatibleEmbedding

__all__ = [
    "OpenAICompatibleEmbedding",
    "OllamaEmbedding",
    "DashScopeEmbedding",
    "DeterministicTestEmbedding",
]

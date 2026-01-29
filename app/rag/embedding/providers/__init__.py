"""
Embedding providers.

Available providers:
- openai: OpenAI-compatible APIs (OpenAI, SiliconFlow, vLLM, etc.)
- ollama: Ollama local embeddings
- dashscope: Alibaba Cloud DashScope
- local: Local sentence-transformers models
"""
from app.rag.embedding.providers.dashscope import DashScopeEmbedding
from app.rag.embedding.providers.local import SentenceTransformerEmbedding
from app.rag.embedding.providers.ollama import OllamaEmbedding
from app.rag.embedding.providers.openai import OpenAICompatibleEmbedding

__all__ = [
    "OpenAICompatibleEmbedding",
    "OllamaEmbedding",
    "DashScopeEmbedding",
    "SentenceTransformerEmbedding",
]

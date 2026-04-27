"""
Embedding providers.

Available providers:
- openai: OpenAI-compatible APIs (OpenAI, SiliconFlow, vLLM, etc.)
- ollama: Ollama local embeddings
- dashscope: Alibaba Cloud DashScope
- local: Local sentence-transformers models
"""
from app.rag.embedding.providers.bedrock import BedrockEmbedding
from app.rag.embedding.providers.cohere import CohereEmbedding
from app.rag.embedding.providers.dashscope import DashScopeEmbedding
from app.rag.embedding.providers.jina import JinaEmbedding
from app.rag.embedding.providers.local import SentenceTransformerEmbedding
from app.rag.embedding.providers.ollama import OllamaEmbedding
from app.rag.embedding.providers.openai import OpenAICompatibleEmbedding
from app.rag.embedding.providers.voyage import VoyageEmbedding

__all__ = [
    "OpenAICompatibleEmbedding",
    "OllamaEmbedding",
    "DashScopeEmbedding",
    "SentenceTransformerEmbedding",
    "VoyageEmbedding",
    "CohereEmbedding",
    "JinaEmbedding",
    "BedrockEmbedding",
]

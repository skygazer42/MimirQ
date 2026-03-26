"""LLM client module for RAG/KG."""
from app.rag.llm.base import BaseLLMClient
from app.rag.llm.factory import EmbeddingClient, OpenAIChatClient, create_llm_client, get_embedding_client
from app.rag.llm.fallback import AllProvidersFailedError, FallbackLLMClient
from app.rag.llm.models import LLMMessage, LLMResponse, LLMRole

__all__ = [
    "BaseLLMClient",
    "FallbackLLMClient",
    "AllProvidersFailedError",
    "LLMMessage",
    "LLMResponse",
    "LLMRole",
    "create_llm_client",
    "get_embedding_client",
    "OpenAIChatClient",
    "EmbeddingClient",
]

"""
Unified AI clients used by non-chat pipelines (e.g., SAG/KG extraction).

This package is the canonical home for the lightweight LLM/embedding adapters
used by the knowledge-graph pipeline. Legacy import paths under `app.rag.llm`
remain as thin compatibility shims.
"""

from app.ai.base import BaseLLMClient
from app.ai.models import LLMMessage, LLMResponse, LLMRole
from app.ai.factory import (
    OpenAIChatClient,
    EmbeddingClient,
    create_llm_client,
    get_embedding_client,
)

__all__ = [
    "BaseLLMClient",
    "LLMMessage",
    "LLMResponse",
    "LLMRole",
    "OpenAIChatClient",
    "EmbeddingClient",
    "create_llm_client",
    "get_embedding_client",
]


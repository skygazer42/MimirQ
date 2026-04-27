"""LLM client module for RAG/KG."""
from app.rag.llm.base import BaseLLMClient
from app.rag.llm.factory import EmbeddingClient, OpenAIChatClient, create_llm_client, get_embedding_client
from app.rag.llm.fallback import AllProvidersFailedError, FallbackLLMClient
from app.rag.llm.models import LLMMessage, LLMResponse, LLMRole
from app.rag.llm.structured_output import (
    build_structured_abstain_payload,
    build_structured_output_instructions,
    parse_and_repair_structured_output,
)

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
    "build_structured_abstain_payload",
    "build_structured_output_instructions",
    "parse_and_repair_structured_output",
]

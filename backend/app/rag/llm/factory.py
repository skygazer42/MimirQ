"""
DEPRECATED: legacy import path for SAG/KG AI clients.

Canonical implementation moved to `app.ai.factory`.
"""

from app.ai.factory import (  # noqa: F401
    OpenAIChatClient,
    EmbeddingClient,
    create_llm_client,
    get_embedding_client,
)

__all__ = [
    "OpenAIChatClient",
    "EmbeddingClient",
    "create_llm_client",
    "get_embedding_client",
]

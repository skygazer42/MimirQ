from __future__ import annotations

from app.rag.embedding.providers.openai import OpenAICompatibleEmbedding


class CohereEmbedding(OpenAICompatibleEmbedding):
    """Cohere embedding wrapper over the OpenAI-compatible client surface."""


__all__ = ["CohereEmbedding"]

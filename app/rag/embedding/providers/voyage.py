from __future__ import annotations

from app.rag.embedding.providers.openai import OpenAICompatibleEmbedding


class VoyageEmbedding(OpenAICompatibleEmbedding):
    """Voyage embedding wrapper over the OpenAI-compatible client surface."""


__all__ = ["VoyageEmbedding"]


from app.rag.embedding.providers.openai import OpenAICompatibleEmbedding


class JinaEmbedding(OpenAICompatibleEmbedding):
    """Jina embedding wrapper over the OpenAI-compatible client surface."""


__all__ = ["JinaEmbedding"]

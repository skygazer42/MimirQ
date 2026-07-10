
from app.rag.embedding.providers.openai import OpenAICompatibleEmbedding


class BedrockEmbedding(OpenAICompatibleEmbedding):
    """Bedrock embedding wrapper over the OpenAI-compatible client surface."""


__all__ = ["BedrockEmbedding"]

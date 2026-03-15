"""
Minimal document processor used by KG recall/expand to generate embeddings.
"""

from app.rag.kg.utils import AIError, get_logger
from app.rag.llm.factory import get_embedding_client

logger = get_logger("kg.load.processor")


class DocumentProcessor:
    """Generate embeddings for text content."""

    def __init__(self, embedding_model_name: str | None = None):
        self.embedding_model_name = embedding_model_name

    async def generate_embedding(self, text: str) -> list[float]:
        try:
            client = await get_embedding_client()
            return await client.generate(text)
        except Exception as exc:
            raise AIError(f"Failed to generate embedding: {exc}") from exc

    async def generate_batch(self, texts: list[str]) -> list[list[float]]:
        try:
            client = await get_embedding_client()
            return await client.generate_batch(texts)
        except Exception as exc:
            raise AIError(f"Failed to generate embeddings batch: {exc}") from exc

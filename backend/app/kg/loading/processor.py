"""
Minimal document processor used by SAG recall/expand to generate embeddings.
"""
from typing import List, Optional

from app.ai.factory import get_embedding_client
from app.kg.utils import AIError, get_logger

logger = get_logger("sag.load.processor")


class DocumentProcessor:
    """Generate embeddings for text content."""

    def __init__(self, embedding_model_name: Optional[str] = None):
        self.embedding_model_name = embedding_model_name

    async def generate_embedding(self, text: str) -> List[float]:
        try:
            client = await get_embedding_client()
            return await client.generate(text)
        except Exception as exc:
            raise AIError(f"Failed to generate embedding: {exc}") from exc

    async def generate_batch(self, texts: List[str]) -> List[List[float]]:
        try:
            client = await get_embedding_client()
            return await client.generate_batch(texts)
        except Exception as exc:
            raise AIError(f"Failed to generate embeddings batch: {exc}") from exc

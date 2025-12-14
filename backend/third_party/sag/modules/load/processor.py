"""
Minimal document processor used by SAG recall/expand to generate embeddings.
"""
from typing import List, Optional

from third_party.sag.core.ai.factory import get_embedding_client
from third_party.sag.exceptions import AIError
from third_party.sag.utils import get_logger

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


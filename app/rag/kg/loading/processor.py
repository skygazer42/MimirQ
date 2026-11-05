"""
Minimal document processor used by KG recall/expand to generate embeddings.
"""

from app.rag.kg.utils import AIError, get_logger
from app.rag.llm.factory import get_embedding_client

logger = get_logger("kg.load.processor")


async def generate_embedding(text: str) -> list[float]:
    try:
        client = await get_embedding_client()
        return await client.generate(text)
    except Exception as exc:
        raise AIError(f"Failed to generate embedding: {exc}") from exc


async def generate_batch(texts: list[str]) -> list[list[float]]:
    try:
        client = await get_embedding_client()
        return await client.generate_batch(texts)
    except Exception as exc:
        raise AIError(f"Failed to generate embeddings batch: {exc}") from exc

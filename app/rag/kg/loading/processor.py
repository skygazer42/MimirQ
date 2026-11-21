"""
Minimal document processor used by KG recall/expand to generate embeddings.
"""

from app.infrastructure.exceptions import AIError
from app.rag.embedding.client import get_embedding_client
from app.rag.embedding.utils import validate_embedding_vectors


async def generate_embedding(text: str) -> list[float]:
    try:
        client = await get_embedding_client()
        return validate_embedding_vectors([await client.generate(text)], count=1)[0]
    except Exception as exc:
        raise AIError(f"Failed to generate embedding: {exc}") from exc


async def generate_batch(texts: list[str]) -> list[list[float]]:
    try:
        client = await get_embedding_client()
        return validate_embedding_vectors(await client.generate_batch(texts), count=len(texts))
    except Exception as exc:
        raise AIError(f"Failed to generate embeddings batch: {exc}") from exc

"""KG load module."""

from app.rag.kg.loading.processor import generate_batch, generate_embedding

__all__ = [
    "generate_embedding",
    "generate_batch",
]

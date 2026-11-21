"""Asynchronous adapter for the active embedding provider."""

from app.infrastructure.config import settings
from app.infrastructure.runtime.async_bridge import run_blocking_in_thread
from app.storage.vector.factory import get_embedding_client as get_active_embedding_client


class EmbeddingClient:
    """Adapter to reuse the project's embedding provider."""

    def __init__(self) -> None:
        self._provider = get_active_embedding_client()

    async def generate(self, text: str) -> list[float]:
        return await self._provider.aembed_query(text)

    async def generate_batch(self, texts: list[str]) -> list[list[float]]:
        batch_limit = min(
            settings.EMBEDDING_API_BATCH_SIZE,
            settings.KG_EXTRACT_EMBED_BATCH_SIZE,
        )
        out: list[list[float]] = []
        for start in range(0, len(texts), batch_limit):
            out.extend(await self._provider.aembed_documents(texts[start : start + batch_limit]))
        return out


async def get_embedding_client() -> EmbeddingClient:
    return await run_blocking_in_thread(EmbeddingClient)

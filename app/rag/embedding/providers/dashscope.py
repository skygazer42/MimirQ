"""
DashScope (Alibaba Cloud) embedding model implementation.

Provides Alibaba Cloud DashScope embedding API support.
"""
import asyncio
import json
from concurrent.futures import ThreadPoolExecutor

import httpx

from app.core.config import settings
from app.rag.embedding.base import BaseEmbeddingModel
from app.rag.embedding.utils import logger


def _run_coroutine_sync(factory):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(factory())

    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(lambda: asyncio.run(factory())).result()


class DashScopeEmbedding(BaseEmbeddingModel):
    """Alibaba Cloud DashScope embedding model.

    Uses DashScope TextEmbedding API for Chinese text embeddings.

    Common models:
    - text-embedding-v4 (1024 dimensions)
    - text-embedding-v3 (1024 dimensions)
    - text-embedding-v2 (768 dimensions)
    """

    def __init__(self, **kwargs):
        """Initialize DashScope embedding model.

        Args:
            model: Model name (e.g., "text-embedding-v4")
            dimension: Embedding vector dimension
            base_url: DashScope API URL (auto-detected if None)
            api_key: DashScope API key (or DASHSCOPE_API_KEY env var)
        """
        super().__init__(**kwargs)

        # Setup headers
        self.headers = {"Content-Type": "application/json"}
        if self.api_key and self.api_key != "no_api_key":
            self.headers["Authorization"] = f"Bearer {self.api_key}"

        # Default DashScope endpoint
        if not self.base_url:
            self.base_url = "https://dashscope.aliyuncs.com/api/v1/services/embeddings/text-embedding/text-embedding"

    def _build_payload(self, message: str | list[str]) -> dict:
        """Build API request payload."""
        if isinstance(message, str):
            message = [message]
        return {"model": self.model, "input": {"texts": message}}

    def _normalize_embeddings(self, vectors: list[list[float]]) -> list[list[float]]:
        """Normalize embeddings to unit length."""
        import numpy as np

        array = np.array(vectors, dtype=float)
        norms = np.linalg.norm(array, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return (array / norms).tolist()

    def encode(self, message: str | list[str]) -> list[list[float]]:
        """Synchronously encode text(s) to embeddings."""
        return _run_coroutine_sync(lambda: self.aencode(message))

    async def aencode(self, message: str | list[str]) -> list[list[float]]:
        """Asynchronously encode text(s) to embeddings."""
        payload = self._build_payload(message)
        timeout = float(getattr(settings, "EMBEDDING_API_TIMEOUT_SEC", 60.0) or 60.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            try:
                response = await client.post(
                    self.base_url, json=payload, headers=self.headers
                )
                response.raise_for_status()
                result = response.json()

                if result.get("code") != "Success":
                    raise ValueError(
                        f"DashScope API error: {result.get('message', 'Unknown error')}"
                    )

                embeddings = [
                    item["embedding"] for item in result["output"]["embeddings"]
                ]
                return self._normalize_embeddings(embeddings)

            except (httpx.RequestError, json.JSONDecodeError, KeyError) as e:
                logger.error(
                    f"DashScope Embedding async request failed: {e}, "
                    f"payload: {payload}, base_url: {self.base_url}"
                )
                raise ValueError(f"DashScope Embedding async request failed: {e}") from e

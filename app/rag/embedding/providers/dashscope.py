"""
DashScope (Alibaba Cloud) embedding model implementation.

Provides Alibaba Cloud DashScope embedding API support.
"""
import contextlib
import json

import httpx

from app.core.config import settings
from app.core.http_client import get_http_client_pool
from app.rag.embedding.base import BaseEmbeddingModel
from app.rag.embedding.utils import logger


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

        pool = get_http_client_pool()
        self.http_client = pool.get_external_sync_client()
        self.http_async_client = pool.get_external_async_client()

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

    def _extract_embeddings(self, result: dict) -> list[list[float]]:
        if result.get("code") != "Success":
            raise ValueError(f"DashScope API error: {result.get('message', 'Unknown error')}")
        vectors = [item["embedding"] for item in result["output"]["embeddings"]]
        return self._normalize_embeddings(vectors)

    def encode(self, message: str | list[str]) -> list[list[float]]:
        """Synchronously encode text(s) to embeddings."""
        payload = self._build_payload(message)
        timeout = float(getattr(settings, "EMBEDDING_API_TIMEOUT_SEC", 60.0) or 60.0)
        response: httpx.Response | None = None
        try:
            response = self.http_client.post(
                self.base_url,
                json=payload,
                headers=self.headers,
                timeout=timeout,
            )
            response.raise_for_status()
            return self._extract_embeddings(response.json())
        except (httpx.RequestError, json.JSONDecodeError, KeyError) as exc:
            logger.error(
                "DashScope Embedding request failed: %s, payload: %s, base_url: %s",
                exc,
                payload,
                self.base_url,
            )
            raise ValueError(f"DashScope Embedding request failed: {exc}") from exc
        finally:
            if response is not None:
                with contextlib.suppress(Exception):
                    response.close()

    async def aencode(self, message: str | list[str]) -> list[list[float]]:
        """Asynchronously encode text(s) to embeddings."""
        payload = self._build_payload(message)
        timeout = float(getattr(settings, "EMBEDDING_API_TIMEOUT_SEC", 60.0) or 60.0)
        response: httpx.Response | None = None
        try:
            response = await self.http_async_client.post(
                self.base_url,
                json=payload,
                headers=self.headers,
                timeout=timeout,
            )
            response.raise_for_status()
            return self._extract_embeddings(response.json())
        except (httpx.RequestError, json.JSONDecodeError, KeyError) as exc:
            logger.error(
                "DashScope Embedding async request failed: %s, payload: %s, base_url: %s",
                exc,
                payload,
                self.base_url,
            )
            raise ValueError(f"DashScope Embedding async request failed: {exc}") from exc
        finally:
            if response is not None:
                with contextlib.suppress(Exception):
                    await response.aclose()

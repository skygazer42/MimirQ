"""
OpenAI-compatible embedding model implementation.

Supports any embedding API that follows the OpenAI embeddings format:
- OpenAI
- SiliconFlow
- DashScope (Alibaba) compatible mode
- OpenRouter
- Local vLLM
- ModelScope
- Any OpenAI-compatible endpoint
"""

from typing import Unpack
from urllib.parse import urlsplit

import httpx

from app.infrastructure.config import settings
from app.infrastructure.http.client import get_http_client_pool
from app.rag.embedding.base import BaseEmbeddingModel, EmbeddingModelOptions
from app.rag.embedding.providers._embedding_http import (
    EmbeddingHTTPConcurrency,
    iter_embedding_batches,
    post_with_retries_async,
    post_with_retries_sync,
)
from app.rag.embedding.utils import decode_embedding_response, logger

DASHSCOPE_BATCH_CAP = 10
SILICONFLOW_QWEN3_VL_BATCH_CAP = 8
_HTTP_CONCURRENCY = EmbeddingHTTPConcurrency()


class OpenAICompatibleEmbedding(BaseEmbeddingModel):
    """OpenAI-compatible embedding model.

    Supports any API following the OpenAI embeddings format:
    - Request: {"model": "...", "input": "..."}
    - Response: {"data": [{"embedding": [...]}]}
    """

    def __init__(
        self,
        *,
        http_client: httpx.Client | None = None,
        http_async_client: httpx.AsyncClient | None = None,
        **kwargs: Unpack[EmbeddingModelOptions],
    ) -> None:
        """Initialize OpenAI-compatible embedding model.

        Args:
            model: Model name (e.g., "text-embedding-3-small", "BAAI/bge-m3")
            dimension: Embedding vector dimension
            base_url: API endpoint URL
            api_key: API key or environment variable name
        """
        super().__init__(**kwargs)

        # Setup headers
        self.headers = {"Content-Type": "application/json"}
        if self.api_key and self.api_key != "no_api_key":
            self.headers["Authorization"] = f"Bearer {self.api_key}"

        # Use shared external HTTP clients (no internal tenant/user headers).
        self.http_client = http_client if http_client is not None else get_http_client_pool().get_external_sync_client()
        self.http_async_client = (
            http_async_client if http_async_client is not None else get_http_client_pool().get_external_async_client()
        )

    def _build_payload(self, message: str | list[str]) -> dict[str, object]:
        """Build API request payload."""
        return {"model": self.model, "input": message}

    def _effective_batch_size(self) -> int:
        configured = settings.EMBEDDING_API_BATCH_SIZE
        if self.base_url is not None and "dashscope.aliyuncs.com" in self.base_url.lower():
            return min(configured, DASHSCOPE_BATCH_CAP)
        if (
            self.model == "Qwen/Qwen3-VL-Embedding-8B"
            and self.base_url is not None
            and urlsplit(self.base_url).hostname == "api.siliconflow.cn"
        ):
            # SiliconFlow restarts response indices after every eighth VL input.
            return min(configured, SILICONFLOW_QWEN3_VL_BATCH_CAP)
        return configured

    def _encode_one_batch(self, texts: list[str]) -> list[list[float]]:
        payload = self._build_payload(texts)
        timeout_sec = settings.EMBEDDING_API_TIMEOUT_SEC
        try:
            return post_with_retries_sync(
                client=self.http_client,
                url=self.base_url,
                request_kwargs={
                    "json": payload,
                    "headers": self.headers,
                    "timeout": timeout_sec,
                },
                parse_response=lambda response: self._parse_response(response, count=len(texts)),
                concurrency=_HTTP_CONCURRENCY,
            )
        except (httpx.HTTPStatusError, httpx.RequestError, KeyError, TypeError, ValueError) as exc:
            msg = f"OpenAI-compatible Embedding request failed: {exc}"
            logger.error("%s", msg)
            raise ValueError(msg) from exc

    def _parse_response(self, response: httpx.Response, *, count: int) -> list[list[float]]:
        result = response.json()
        if not isinstance(result, dict) or "data" not in result:
            raise ValueError("Embeddings response must contain a data array")
        return decode_embedding_response(result["data"], count=count, dimension=self.dimension)

    def encode(self, message: str | list[str]) -> list[list[float]]:
        """Synchronously encode text(s) to embeddings."""
        out: list[list[float]] = []
        for batch in iter_embedding_batches(message, self._effective_batch_size()):
            out.extend(self._encode_one_batch(batch))
        return out

    async def _aencode_one_batch(self, texts: list[str]) -> list[list[float]]:
        payload = self._build_payload(texts)
        timeout_sec = settings.EMBEDDING_API_TIMEOUT_SEC
        try:
            return await post_with_retries_async(
                client=self.http_async_client,
                url=self.base_url,
                request_kwargs={
                    "json": payload,
                    "headers": self.headers,
                    "timeout": timeout_sec,
                },
                parse_response=lambda response: self._parse_response(response, count=len(texts)),
                concurrency=_HTTP_CONCURRENCY,
            )
        except (httpx.HTTPStatusError, httpx.RequestError, KeyError, TypeError, ValueError) as exc:
            msg = f"OpenAI-compatible Embedding async request failed: {exc}"
            logger.error("%s", msg)
            raise ValueError(msg) from exc

    async def aencode(self, message: str | list[str]) -> list[list[float]]:
        """Asynchronously encode text(s) to embeddings."""
        out: list[list[float]] = []
        for batch in iter_embedding_batches(message, self._effective_batch_size()):
            out.extend(await self._aencode_one_batch(batch))
        return out

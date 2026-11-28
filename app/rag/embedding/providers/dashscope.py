"""DashScope native and OpenAI-compatible embedding protocols."""

from typing import Unpack
from urllib.parse import urlsplit

import httpx

from app.rag.embedding.base import EmbeddingModelOptions
from app.rag.embedding.providers.openai import DASHSCOPE_BATCH_CAP, OpenAICompatibleEmbedding
from app.rag.embedding.utils import decode_embedding_response, normalize_embedding_vectors

_NATIVE_ENDPOINT = "https://dashscope.aliyuncs.com/api/v1/services/embeddings/text-embedding/text-embedding"


class DashScopeEmbedding(OpenAICompatibleEmbedding):
    """Share HTTP ownership and batching; adapt only DashScope's wire format."""

    def __init__(
        self,
        *,
        http_client: httpx.Client | None = None,
        http_async_client: httpx.AsyncClient | None = None,
        **kwargs: Unpack[EmbeddingModelOptions],
    ) -> None:
        super().__init__(http_client=http_client, http_async_client=http_async_client, **kwargs)
        if not self.base_url:
            self.base_url = _NATIVE_ENDPOINT
        self._compatible_mode = urlsplit(self.base_url).path.rstrip("/").endswith("/v1/embeddings")

    def _effective_batch_size(self) -> int:
        return min(super()._effective_batch_size(), DASHSCOPE_BATCH_CAP)

    def _build_payload(self, message: str | list[str]) -> dict[str, object]:
        if self._compatible_mode:
            return super()._build_payload(message)
        texts = [message] if isinstance(message, str) else message
        return {"model": self.model, "input": {"texts": texts}}

    def _parse_response(self, response: httpx.Response, *, count: int) -> list[list[float]]:
        if self._compatible_mode:
            return super()._parse_response(response, count=count)
        result = response.json()
        vectors = decode_embedding_response(result["output"]["embeddings"], count=count, dimension=self.dimension)
        return normalize_embedding_vectors(vectors)

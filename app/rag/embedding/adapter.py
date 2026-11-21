"""
LangChain-compatible embeddings adapter.

Adapts app.rag.embedding models to LangChain's Embeddings interface
for use with Milvus and the development memory vector store.
"""

import hashlib
import json
from typing import TYPE_CHECKING

import httpx
from langchain_core.embeddings import Embeddings
from redis.exceptions import RedisError

from app.infrastructure.config import settings
from app.infrastructure.redis.client import LazyRedisClient
from app.infrastructure.runtime.async_bridge import run_blocking_in_thread
from app.rag.embedding.base import BaseEmbeddingModel
from app.rag.embedding.utils import (
    current_embedding_space_hash,
    embedding_space_hash_for_config,
    logger,
    normalize_embedding_vectors,
    validate_embedding_vectors,
)
from app.services.observability.metrics_log import log_metrics

if TYPE_CHECKING:
    from redis import Redis

_redis_client_slot = LazyRedisClient(
    url=lambda: settings.REDIS_URL,
    kwargs={
        "socket_timeout": 1,
        "socket_connect_timeout": 1,
        "decode_responses": False,
    },
    on_error=lambda exc: logger.warning(
        "Embedding cache disabled (redis init failed): %s",
        str(exc)[:200],
    ),
)
_get_redis_client = _redis_client_slot.get
_invalidate_redis_client = _redis_client_slot.invalidate


def _embed_cache_key(text: str, *, space: str | None = None) -> str:
    # Bind to the current embedding "space" (provider/model/base_url) to avoid serving
    # incompatible vectors after a model/endpoint change.
    space = current_embedding_space_hash() if space is None else space
    digest = hashlib.sha256(text.encode("utf-8", "ignore")).hexdigest()
    prefix = settings.EMBEDDING_CACHE_PREFIX
    return ":".join((prefix, space, digest))


def _document_cache_client() -> "Redis | None":
    if settings.EMBEDDING_CACHE_ENABLED:
        return _get_redis_client()
    return None


def _write_cached_vectors(
    *,
    client: "Redis",
    keys: list[str],
    vectors: list[list[float]],
) -> None:
    payloads = [json.dumps(vector, separators=(",", ":"), allow_nan=False).encode("utf-8") for vector in vectors]
    ttl = settings.EMBEDDING_CACHE_TTL_SEC
    try:
        with client.pipeline(transaction=False) as pipe:
            for key, payload in zip(keys, payloads, strict=True):
                if ttl > 0:
                    pipe.set(key, payload, ex=ttl)
                else:
                    pipe.set(key, payload)
            pipe.execute()
    except RedisError as exc:
        logger.warning("Embedding cache write failed: %s", type(exc).__name__)
        _invalidate_redis_client()


def _log_cache_metrics(*, op: str, total: int, hits: int, misses: int, corrupt: int) -> None:
    try:
        log_metrics(
            {
                "event": "embedding.cache",
                "op": op,
                "total": total,
                "hits": hits,
                "misses": misses,
                "corrupt": corrupt,
            }
        )
    except Exception as exc:
        logger.debug("Ignoring non-critical embedding adapter fallback failure: %s", exc)


class LangChainEmbeddingsAdapter(Embeddings):
    """LangChain Embeddings interface adapter.

    Adapts any BaseEmbeddingModel to LangChain's expected interface:
    - embed_documents(texts: List[str]) -> List[List[float]]
    - embed_query(text: str) -> List[float]

    Usage:
        from app.rag.embedding import select_embedding_model
        from app.rag.embedding.adapter import LangChainEmbeddingsAdapter

        model = select_embedding_model("ollama/nomic-embed-text")
        embeddings = LangChainEmbeddingsAdapter(model)

        # Use with LangChain vector stores
        from langchain_community.vectorstores import Milvus
        vectorstore = Milvus(embedding_function=embeddings, ...)
    """

    def __init__(
        self,
        model: BaseEmbeddingModel,
        normalize: bool = True,
        cache_space_hash: str | None = None,
        *,
        use_cache: bool = True,
    ) -> None:
        """Initialize the adapter.

        Args:
            model: BaseEmbeddingModel instance
            normalize: Whether to normalize embeddings (default: True)
        """
        self._model = model
        self._normalize = normalize
        self._dimension = model.dimension
        self._cache_space_hash = cache_space_hash
        if cache_space_hash is None:
            self._cache_space_hash = embedding_space_hash_for_config(
                provider=type(model).__name__, model=model.model, base_url=model.base_url
            )
        self._use_cache = use_cache

    def _cache_key(self, text: str) -> str:
        return _embed_cache_key(text, space=self._cache_space_hash)

    def _embed(self, texts: list[str], *, op: str) -> list[list[float]]:
        """Compute missing vectors and replace corrupt optional cache entries."""
        if not texts:
            return []
        client = _document_cache_client() if self._use_cache else None
        cache_hits = 0
        cache_misses = 0
        cache_corrupt = 0
        if client is None:
            embeddings = self._model.encode(texts)
        else:
            keys = [self._cache_key(text) for text in texts]
            try:
                cached_raw = client.mget(keys)
            except RedisError as exc:
                logger.warning("Embedding cache read failed: %s", type(exc).__name__)
                _invalidate_redis_client()
                cached_raw = [None] * len(texts)

            vectors_by_index: dict[int, list[float]] = {}
            missing: list[int] = []
            for index, raw in enumerate(cached_raw):
                if raw is not None:
                    try:
                        vectors_by_index[index] = validate_embedding_vectors(
                            [json.loads(raw)], count=1, dimension=self._dimension
                        )[0]
                    except ValueError:
                        cache_corrupt += 1
                    else:
                        cache_hits += 1
                        continue
                missing.append(index)
            cache_misses = len(missing)
            if missing:
                computed = validate_embedding_vectors(
                    self._model.encode([texts[index] for index in missing]),
                    count=len(missing),
                    dimension=self._dimension,
                )
                vectors_by_index.update(zip(missing, computed, strict=True))

            embeddings = [vectors_by_index[index] for index in range(len(texts))]
            if self._dimension is None:
                embeddings = validate_embedding_vectors(embeddings, count=len(texts))
            if missing:
                _write_cached_vectors(
                    client=client,
                    keys=[keys[index] for index in missing],
                    vectors=[embeddings[index] for index in missing],
                )

        _log_cache_metrics(op=op, total=len(texts), hits=cache_hits, misses=cache_misses, corrupt=cache_corrupt)
        return normalize_embedding_vectors(embeddings) if self._normalize else embeddings

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._embed(texts, op="documents")

    def embed_query(self, text: str) -> list[float]:
        return self._embed([text], op="query")[0]

    @property
    def dimension(self) -> int | None:
        """Get the embedding dimension."""
        return self._dimension

    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        """Use native provider IO, retaining the existing synchronous cache boundary."""
        if self._use_cache and settings.EMBEDDING_CACHE_ENABLED:
            return await run_blocking_in_thread(self.embed_documents, texts)
        if not texts:
            return []
        vectors = await self._model.aencode(texts)
        return normalize_embedding_vectors(vectors) if self._normalize else vectors

    async def aembed_query(self, text: str) -> list[float]:
        if self._use_cache and settings.EMBEDDING_CACHE_ENABLED:
            return await run_blocking_in_thread(self.embed_query, text)
        vectors = await self._model.aencode([text])
        if self._normalize:
            vectors = normalize_embedding_vectors(vectors)
        return vectors[0]


def create_langchain_embeddings(model_id: str, normalize: bool = True) -> LangChainEmbeddingsAdapter:
    """Create a LangChain-compatible embeddings instance.

    Convenience function to create embeddings adapter from model_id.

    Args:
        model_id: Model identifier (e.g., "ollama/nomic-embed-text")
        normalize: Whether to normalize embeddings

    Returns:
        LangChainEmbeddingsAdapter instance

    Examples:
        from app.rag.embedding.adapter import create_langchain_embeddings

        embeddings = create_langchain_embeddings("ollama/nomic-embed-text")
        vectors = embeddings.embed_documents(["Hello", "World"])
    """
    from app.rag.embedding.factory import select_embedding_model

    model = select_embedding_model(model_id)
    return LangChainEmbeddingsAdapter(model, normalize=normalize)


def create_langchain_embeddings_from_config(
    provider: str,
    model: str,
    api_key: str | None = None,
    base_url: str | None = None,
    dimension: int | None = None,
    cache_space_hash: str | None = None,
    *,
    http_client: httpx.Client | None = None,
    http_async_client: httpx.AsyncClient | None = None,
    use_cache: bool = True,
) -> LangChainEmbeddingsAdapter:
    """Create configured embeddings, borrowing explicitly supplied HTTP clients.

    Args:
        provider: Service provider name (e.g., "openai_compatible", "dashscope")
        model: Model name
        api_key: API key (optional)
        base_url: API base URL (optional)
        dimension: Embedding dimension (optional)
        http_client: Optional caller-owned synchronous transport.
        http_async_client: Optional caller-owned transport for the caller's event loop.

    Returns:
        LangChainEmbeddingsAdapter instance
    """
    from app.infrastructure.model_policy import reject_retired_provider
    from app.rag.embedding.providers import (
        DashScopeEmbedding,
        DeterministicTestEmbedding,
        OllamaEmbedding,
        OpenAICompatibleEmbedding,
    )

    provider = provider.lower()
    reject_retired_provider(provider, capability="embedding")
    if base_url is not None:
        base_url = base_url.strip()
    if provider in {"openai", "openai_compatible", "dashscope"} and base_url is not None:
        stripped = base_url.rstrip("/")
        if stripped.endswith("/v1"):
            base_url = stripped + "/embeddings"

    embedding_model: BaseEmbeddingModel
    if provider == "deterministic_test":
        embedding_model = DeterministicTestEmbedding(model=model, dimension=dimension)
    else:
        provider_class = {"dashscope": DashScopeEmbedding, "ollama": OllamaEmbedding}.get(
            provider, OpenAICompatibleEmbedding
        )
        embedding_model = provider_class(
            model=model,
            dimension=dimension,
            base_url=base_url,
            api_key=api_key,
            http_client=http_client,
            http_async_client=http_async_client,
        )

    return LangChainEmbeddingsAdapter(
        embedding_model, normalize=True, cache_space_hash=cache_space_hash, use_cache=use_cache
    )

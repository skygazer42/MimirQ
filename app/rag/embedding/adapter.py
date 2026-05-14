"""
LangChain-compatible embeddings adapter.

Adapts app.rag.embedding models to LangChain's Embeddings interface
for use with LangChain vector stores (Milvus, FAISS, Chroma, etc.).
"""

import hashlib
import json

from app.core.config import settings
from app.rag.embedding.base import BaseEmbeddingModel
from app.rag.embedding.utils import current_embedding_space_hash, logger
from app.services.metrics_logger import log_metrics

_redis_client = None


def _get_redis_client():
    global _redis_client
    if _redis_client is not None:
        return _redis_client
    try:
        import redis  # type: ignore

        _redis_client = redis.Redis.from_url(
            settings.REDIS_URL,
            socket_timeout=1,
            socket_connect_timeout=1,
            decode_responses=False,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Embedding cache disabled (redis init failed): %s", str(exc)[:200])
        _redis_client = None
    return _redis_client


def _invalidate_redis_client() -> None:
    global _redis_client
    _redis_client = None


def _embed_cache_key(text: str, *, space: str | None = None) -> str:
    # Bind to the current embedding "space" (provider/model/base_url) to avoid serving
    # incompatible vectors after a model/endpoint change.
    space = space or current_embedding_space_hash()
    digest = hashlib.sha256(text.encode("utf-8", "ignore")).hexdigest()
    prefix = getattr(settings, "EMBEDDING_CACHE_PREFIX", "emb")
    return f"{prefix}:{space}:{digest}"


class LangChainEmbeddingsAdapter:
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

    def __init__(self, model: BaseEmbeddingModel, normalize: bool = True, cache_space_hash: str | None = None):
        """Initialize the adapter.

        Args:
            model: BaseEmbeddingModel instance
            normalize: Whether to normalize embeddings (default: True)
        """
        self._model = model
        self._normalize = normalize
        self._dimension = model.dimension
        self._cache_space_hash = str(cache_space_hash or "").strip() or None

    def _cache_key(self, text: str) -> str:
        if self._cache_space_hash:
            return _embed_cache_key(text, space=self._cache_space_hash)
        return _embed_cache_key(text)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed a list of text documents.

        Args:
            texts: List of text strings

        Returns:
            List of embedding vectors
        """
        # Best-effort Redis cache to avoid repeated embedding calls during ingest.
        if bool(getattr(settings, "EMBEDDING_CACHE_ENABLED", True)):
            client = _get_redis_client()
        else:
            client = None

        if not texts:
            return []

        embeddings: list[list[float]]
        if client is None:
            embeddings = self._model.encode(texts)
        else:
            keys = [self._cache_key(t) for t in texts]
            try:
                cached_raw = client.mget(keys)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Embedding cache read failed (mget): %s", str(exc)[:200])
                _invalidate_redis_client()
                cached_raw = None

            if cached_raw is None:
                embeddings = self._model.encode(texts)
                if self._normalize:
                    embeddings = self._normalize_vectors(embeddings)
                return embeddings

            cache_hits = 0
            cache_misses = 0
            cache_corrupt = 0

            missing: list[tuple[int, str]] = []
            out: list[list[float] | None] = [None] * len(texts)
            for i, raw in enumerate(cached_raw):
                if raw:
                    try:
                        out[i] = json.loads(raw)
                        cache_hits += 1
                    except Exception:  # noqa: BLE001
                        cache_corrupt += 1
                        cache_misses += 1
                        missing.append((i, texts[i]))
                else:
                    cache_misses += 1
                    missing.append((i, texts[i]))

            if missing:
                missing_texts = [t for _, t in missing]
                computed = self._model.encode(missing_texts)
                ttl = int(getattr(settings, "EMBEDDING_CACHE_TTL_SEC", 7 * 24 * 3600) or 0)
                try:
                    pipe = client.pipeline(transaction=False)
                    for (idx, _t), vec in zip(missing, computed, strict=False):
                        out[idx] = vec
                        try:
                            payload = json.dumps(vec, separators=(",", ":")).encode("utf-8")
                            if ttl > 0:
                                pipe.set(keys[idx], payload, ex=ttl)
                            else:
                                pipe.set(keys[idx], payload)
                        except Exception:  # noqa: BLE001
                            # Cache failures do not affect main flow.
                            pass
                    try:
                        pipe.execute()
                    except Exception:  # noqa: BLE001
                        _invalidate_redis_client()
                except Exception:  # noqa: BLE001
                    _invalidate_redis_client()

            embeddings = [v if v is not None else [] for v in out]
            try:
                log_metrics(
                    {
                        "event": "embedding.cache",
                        "op": "documents",
                        "total": int(len(texts)),
                        "hits": int(cache_hits),
                        "misses": int(cache_misses),
                        "corrupt": int(cache_corrupt),
                    }
                )
            except Exception as exc:
                logger.debug("Ignoring non-critical embedding adapter fallback failure: %s", exc)

        if self._normalize:
            embeddings = self._normalize_vectors(embeddings)

        return embeddings

    def embed_query(self, text: str) -> list[float]:
        """Embed a single query text.

        Args:
            text: Query text string

        Returns:
            Embedding vector
        """
        if bool(getattr(settings, "EMBEDDING_CACHE_ENABLED", True)):
            client = _get_redis_client()
        else:
            client = None

        cache_hits = 0
        cache_misses = 0

        if client is None:
            embeddings = self._model.encode([text])
        else:
            key = self._cache_key(text)
            try:
                raw = client.get(key)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Embedding cache read failed (get): %s", str(exc)[:200])
                _invalidate_redis_client()
                raw = None
            if raw:
                try:
                    vec = json.loads(raw)
                    embeddings = [vec]
                    cache_hits = 1
                except Exception:  # noqa: BLE001
                    cache_misses = 1
                    embeddings = self._model.encode([text])
            else:
                cache_misses = 1
                embeddings = self._model.encode([text])
                try:
                    ttl = int(getattr(settings, "EMBEDDING_CACHE_TTL_SEC", 7 * 24 * 3600) or 0)
                    payload = json.dumps(embeddings[0], separators=(",", ":")).encode("utf-8")
                    if ttl > 0:
                        client.set(key, payload, ex=ttl)
                    else:
                        client.set(key, payload)
                except Exception:  # noqa: BLE001
                    _invalidate_redis_client()

        try:
            log_metrics(
                {
                    "event": "embedding.cache",
                    "op": "query",
                    "total": 1,
                    "hits": int(cache_hits),
                    "misses": int(cache_misses),
                }
            )
        except Exception as exc:
            logger.debug("Ignoring non-critical embedding adapter fallback failure: %s", exc)

        if self._normalize:
            embeddings = self._normalize_vectors(embeddings)

        return embeddings[0]

    def _normalize_vectors(self, vectors: list[list[float]]) -> list[list[float]]:
        """Normalize embeddings to unit length."""
        import numpy as np

        array = np.array(vectors, dtype=float)
        norms = np.linalg.norm(array, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return (array / norms).tolist()

    @property
    def dimension(self) -> int:
        """Get the embedding dimension."""
        return self._dimension


def create_langchain_embeddings(
    model_id: str, normalize: bool = True
) -> LangChainEmbeddingsAdapter:
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
    api_key: str = "",
    base_url: str = "",
    dimension: int = None,
    cache_space_hash: str | None = None,
) -> LangChainEmbeddingsAdapter:
    """Create LangChain embeddings from config (for compatibility with milvus.py).

    This function provides backward compatibility with the old embedding setup
    in app/storage/vector/milvus.py.

    Args:
        provider: Provider name (e.g., "local", "openai_compatible", "dashscope")
        model: Model name
        api_key: API key (optional)
        base_url: API base URL (optional)
        dimension: Embedding dimension (optional)

    Returns:
        LangChainEmbeddingsAdapter instance
    """
    from app.rag.embedding.providers import (
        DashScopeEmbedding,
        OllamaEmbedding,
        OpenAICompatibleEmbedding,
        SentenceTransformerEmbedding,
    )

    provider = provider.lower()
    base_url = (base_url or "").strip()
    if provider in {"openai", "openai_compatible", "dashscope"}:
        stripped = base_url.rstrip("/")
        if stripped.endswith("/v1"):
            base_url = stripped + "/embeddings"

    if provider == "local":
        embedding_model = SentenceTransformerEmbedding(
            model=model, dimension=dimension, base_url=base_url, api_key=api_key
        )
    elif provider == "dashscope":
        embedding_model = DashScopeEmbedding(
            model=model, dimension=dimension, base_url=base_url, api_key=api_key
        )
    elif provider == "ollama":
        embedding_model = OllamaEmbedding(
            model=model, dimension=dimension, base_url=base_url, api_key=api_key
        )
    else:  # openai_compatible, openai, etc.
        embedding_model = OpenAICompatibleEmbedding(
            model=model, dimension=dimension, base_url=base_url, api_key=api_key
        )

    return LangChainEmbeddingsAdapter(embedding_model, normalize=True, cache_space_hash=cache_space_hash)

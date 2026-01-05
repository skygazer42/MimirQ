"""
LangChain-compatible embeddings adapter.

Adapts app.rag.embedding models to LangChain's Embeddings interface
for use with LangChain vector stores (Milvus, FAISS, Chroma, etc.).
"""
from __future__ import annotations

from typing import List, Optional, Dict, Any, Tuple
import hashlib
import json

from app.rag.embedding.base import BaseEmbeddingModel
from app.rag.embedding.utils import logger
from app.core.config import settings

_redis_client = None


def _get_redis_client():
    global _redis_client
    if _redis_client is not None:
        return _redis_client
    try:
        import redis  # type: ignore

        _redis_client = redis.Redis.from_url(settings.REDIS_URL)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Embedding cache disabled (redis init failed): %s", str(exc)[:200])
        _redis_client = None
    return _redis_client


def _embed_cache_key(text: str) -> str:
    # 绑定模型与版本（当前使用 provider/model；未来如有显式版本，可追加）
    model_key = f"{settings.EMBEDDING_PROVIDER}/{settings.EMBEDDING_MODEL}"
    digest = hashlib.sha256(text.encode("utf-8", "ignore")).hexdigest()
    prefix = getattr(settings, "EMBEDDING_CACHE_PREFIX", "emb")
    return f"{prefix}:{model_key}:{digest}"


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

    def __init__(self, model: BaseEmbeddingModel, normalize: bool = True):
        """Initialize the adapter.

        Args:
            model: BaseEmbeddingModel instance
            normalize: Whether to normalize embeddings (default: True)
        """
        self._model = model
        self._normalize = normalize
        self._dimension = model.dimension

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
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

        embeddings: List[List[float]]
        if client is None:
            embeddings = self._model.encode(texts)
        else:
            keys = [_embed_cache_key(t) for t in texts]
            cached_raw = client.mget(keys)

            missing: List[Tuple[int, str]] = []
            out: List[Optional[List[float]]] = [None] * len(texts)
            for i, raw in enumerate(cached_raw):
                if raw:
                    try:
                        out[i] = json.loads(raw)
                    except Exception:  # noqa: BLE001
                        missing.append((i, texts[i]))
                else:
                    missing.append((i, texts[i]))

            if missing:
                missing_texts = [t for _, t in missing]
                computed = self._model.encode(missing_texts)
                ttl = int(getattr(settings, "EMBEDDING_CACHE_TTL_SEC", 7 * 24 * 3600) or 0)
                pipe = client.pipeline(transaction=False)
                for (idx, _t), vec in zip(missing, computed):
                    out[idx] = vec
                    try:
                        payload = json.dumps(vec, separators=(",", ":")).encode("utf-8")
                        if ttl > 0:
                            pipe.set(keys[idx], payload, ex=ttl)
                        else:
                            pipe.set(keys[idx], payload)
                    except Exception:  # noqa: BLE001
                        # 缓存失败不影响主流程
                        pass
                try:
                    pipe.execute()
                except Exception:  # noqa: BLE001
                    pass

            embeddings = [v if v is not None else [] for v in out]

        if self._normalize:
            embeddings = self._normalize_vectors(embeddings)

        return embeddings

    def embed_query(self, text: str) -> List[float]:
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

        if client is None:
            embeddings = self._model.encode([text])
        else:
            key = _embed_cache_key(text)
            raw = client.get(key)
            if raw:
                try:
                    vec = json.loads(raw)
                    embeddings = [vec]
                except Exception:  # noqa: BLE001
                    embeddings = self._model.encode([text])
            else:
                embeddings = self._model.encode([text])
                try:
                    ttl = int(getattr(settings, "EMBEDDING_CACHE_TTL_SEC", 7 * 24 * 3600) or 0)
                    payload = json.dumps(embeddings[0], separators=(",", ":")).encode("utf-8")
                    if ttl > 0:
                        client.set(key, payload, ex=ttl)
                    else:
                        client.set(key, payload)
                except Exception:  # noqa: BLE001
                    pass

        if self._normalize:
            embeddings = self._normalize_vectors(embeddings)

        return embeddings[0]

    def _normalize_vectors(self, vectors: List[List[float]]) -> List[List[float]]:
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
    provider: str, model: str, api_key: str = "", base_url: str = "", dimension: int = None
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
        SentenceTransformerEmbedding,
        OpenAICompatibleEmbedding,
        DashScopeEmbedding,
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
    else:  # openai_compatible, openai, etc.
        embedding_model = OpenAICompatibleEmbedding(
            model=model, dimension=dimension, base_url=base_url, api_key=api_key
        )

    return LangChainEmbeddingsAdapter(embedding_model, normalize=True)

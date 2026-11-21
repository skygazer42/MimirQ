"""
Embedding utility functions.
"""

import hashlib
import logging
import os
from typing import Annotated, NotRequired, TypedDict
from urllib.parse import urlsplit, urlunsplit

from pydantic import AliasChoices, ConfigDict, Field, FiniteFloat, TypeAdapter

from app.infrastructure.model_policy import EmbeddingProviders

logger = logging.getLogger("rag.embedding")
_VECTORS = TypeAdapter(
    list[Annotated[list[FiniteFloat], Field(min_length=1)]],
    config=ConfigDict(strict=True, hide_input_in_errors=True),
)


class _EmbeddingItem(TypedDict):
    embedding: object
    index: NotRequired[Annotated[int, Field(ge=0, validation_alias=AliasChoices("index", "text_index"))]]


_EMBEDDING_ITEMS = TypeAdapter(list[_EmbeddingItem], config=ConfigDict(strict=True, hide_input_in_errors=True))


def decode_embedding_response(value: object, *, count: int, dimension: int | None) -> list[list[float]]:
    """Use provider indexes when present; index-free compatible APIs retain their order."""
    items = _EMBEDDING_ITEMS.validate_python(value)
    indexed = {item.get("index", position): item["embedding"] for position, item in enumerate(items)}
    if len(items) != count or len(indexed) != count or any(index >= count for index in indexed):
        raise ValueError("Embedding response indexes do not match the requested batch")
    return validate_embedding_vectors([indexed[index] for index in range(count)], count=count, dimension=dimension)


def validate_embedding_vectors(value: object, *, count: int, dimension: int | None = None) -> list[list[float]]:
    """Validate one external batch without changing its row order or vector space."""
    vectors = _VECTORS.validate_python(value)
    if len(vectors) != count:
        raise ValueError(f"Embedding count mismatch: expected {count}, got {len(vectors)}")
    if not vectors:
        return vectors
    expected_dimension = len(vectors[0]) if dimension is None else dimension
    if any(len(vector) != expected_dimension for vector in vectors):
        raise ValueError(f"Embedding dimension mismatch: expected {expected_dimension}")
    return vectors


def normalize_embedding_vectors(vectors: list[list[float]]) -> list[list[float]]:
    """Normalize embedding vectors to unit length, preserving zero vectors."""
    import numpy as np

    if not vectors:
        return []
    array = np.array(vectors, dtype=float)
    norms = np.linalg.norm(array, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return (array / norms).tolist()


def hashstr(input_string: str, length: int | None = None) -> str:
    """Generate a stable hash of a string.

    Args:
        input_string: Input string to hash
        length: Optional length to truncate the hash to

    Returns:
        Hash string (hex format)
    """
    encoded_string = input_string.encode("utf-8", errors="replace")

    # BLAKE2 is fast and avoids weak-hash hotspots (e.g. MD5) while keeping a compact digest.
    hash_value = hashlib.blake2b(encoded_string, digest_size=16).hexdigest()
    if length is not None:
        return hash_value[:length]
    return hash_value


def get_docker_safe_url(base_url: str | None) -> str | None:
    """Convert URL for Docker internal networking.

    Replaces localhost/127.0.0.1 with host.docker.internal
    when running inside Docker.

    Args:
        base_url: Original URL

    Returns:
        Docker-safe URL
    """
    if not base_url:
        return base_url

    if os.getenv("RUNNING_IN_DOCKER") == "true":
        parsed = urlsplit(base_url)
        if parsed.hostname in {"localhost", "127.0.0.1"}:
            userinfo = parsed.netloc.rpartition("@")[0]
            if userinfo:
                userinfo += "@"
            port = f":{parsed.port}" if parsed.port is not None else ""
            netloc = f"{userinfo}host.docker.internal{port}"
            base_url = urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))
            logger.info("Using host.docker.internal for Docker embedding endpoint")
    return base_url


def current_embedding_space_hash(*, length: int | None = 16) -> str:
    """
    Return a stable hash for the current embedding "space" (model/provider endpoint).

    Why:
    - In real deployments, embedding model/provider/base_url can change over time.
    - Vector similarity across different embedding spaces is meaningless and can silently
      degrade retrieval quality (or cause confusing relevance).

    Notes:
    - We intentionally DO NOT include API keys.
    - We best-effort normalize base_url to reduce accidental cache busting.
    """
    # Lazy import to avoid import cycles at module import time.
    from app.infrastructure.config import settings

    return embedding_space_hash_for_config(
        provider=settings.EMBEDDING_PROVIDER,
        model=settings.EMBEDDING_MODEL,
        base_url=settings.EMBEDDING_API_BASE or settings.LLM_API_BASE,
        length=length,
    )


def embedding_space_hash_for_config(
    *,
    provider: str | None,
    model: str | None,
    base_url: str | None,
    length: int | None = 16,
) -> str:
    """
    Return a stable embedding-space hash for an explicit config tuple.

    This is a utility for "blue-green" embedding migrations where we may need to
    compute the space hash for a *shadow* embedding model without mutating global
    settings (Gap5).
    """
    provider_raw = (provider or "openai_compatible").strip().lower()
    mapped_provider = EmbeddingProviders.PROVIDER_MAP.get(provider_raw, provider_raw)
    model0 = (model or "").strip()
    base = (base_url or "").strip()

    norm_base = ""
    if base:
        parsed = urlsplit(base)
        norm_base = f"{parsed.scheme}://{parsed.netloc}{parsed.path}".rstrip("/")

    key = f"provider={mapped_provider}|model={model0}|base_url={norm_base}"
    return hashstr(key, length=length)


__all__ = [
    "current_embedding_space_hash",
    "decode_embedding_response",
    "embedding_space_hash_for_config",
    "get_docker_safe_url",
    "hashstr",
    "normalize_embedding_vectors",
    "validate_embedding_vectors",
]

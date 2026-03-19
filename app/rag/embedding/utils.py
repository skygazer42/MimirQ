"""
Embedding utility functions.
"""
import hashlib
import os
from urllib.parse import urlsplit

from app.core.constants import EmbeddingProviders
from app.rag.core.logging import get_logger

logger = get_logger("rag.embedding")


def hashstr(input_string: str, length: int | None = None) -> str:
    """Generate MD5 hash of a string.

    Args:
        input_string: Input string to hash
        length: Optional length to truncate the hash to

    Returns:
        Hash string (hex format)
    """
    try:
        encoded_string = str(input_string).encode("utf-8")
    except UnicodeEncodeError:
        encoded_string = str(input_string).encode("utf-8", errors="replace")

    hash_value = hashlib.md5(encoded_string).hexdigest()
    if length:
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
        base_url = base_url.replace("http://localhost", "http://host.docker.internal")
        base_url = base_url.replace("http://127.0.0.1", "http://host.docker.internal")
        logger.info(f"Running in docker, using {base_url} as base url")
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
    from app.core.config import settings

    provider_raw = (settings.EMBEDDING_PROVIDER or "openai_compatible").strip().lower()
    provider = EmbeddingProviders.PROVIDER_MAP.get(provider_raw, provider_raw)
    model = (settings.EMBEDDING_MODEL or "").strip()
    base_url = (settings.EMBEDDING_API_BASE or settings.LLM_API_BASE or "").strip()

    # Normalize base_url: keep scheme/host/path, drop query/fragment.
    norm_base = ""
    if base_url:
        try:
            u = urlsplit(base_url)
            norm_base = f"{u.scheme}://{u.netloc}{u.path}".rstrip("/")
        except Exception:
            norm_base = base_url.rstrip("/")

    key = f"provider={provider}|model={model}|base_url={norm_base}"
    return hashstr(key, length=length)


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
        try:
            u = urlsplit(base)
            norm_base = f"{u.scheme}://{u.netloc}{u.path}".rstrip("/")
        except Exception:
            norm_base = base.rstrip("/")

    key = f"provider={mapped_provider}|model={model0}|base_url={norm_base}"
    return hashstr(key, length=length)


__all__ = [
    "current_embedding_space_hash",
    "embedding_space_hash_for_config",
    "get_docker_safe_url",
    "hashstr",
]

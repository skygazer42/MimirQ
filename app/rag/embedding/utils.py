"""
Embedding utility functions.
"""

import hashlib
import os
from urllib.parse import urlsplit, urlunsplit

from app.core.constants import EmbeddingProviders
from app.rag.core.logging import get_logger

logger = get_logger("rag.embedding")


def hashstr(input_string: str, length: int | None = None) -> str:
    """Generate a stable hash of a string.

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

    # BLAKE2 is fast and avoids weak-hash hotspots (e.g. MD5) while keeping a compact digest.
    hash_value = hashlib.blake2b(encoded_string, digest_size=16).hexdigest()
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
        updated = base_url
        try:
            u = urlsplit(base_url)
            if u.scheme and u.netloc and u.hostname in {"localhost", "127.0.0.1"}:
                # Preserve scheme/userinfo/port/path/query/fragment.
                userinfo = ""
                if u.username:
                    userinfo = u.username
                    if u.password:
                        userinfo += f":{u.password}"
                    userinfo += "@"
                port = f":{u.port}" if u.port else ""
                netloc = f"{userinfo}host.docker.internal{port}"
                updated = urlunsplit((u.scheme, netloc, u.path, u.query, u.fragment))
        except Exception:
            # Best-effort fallback: keep the scheme and just swap the hostname.
            updated = updated.replace("localhost", "host.docker.internal").replace("127.0.0.1", "host.docker.internal")

        if updated != base_url:
            logger.info("Running in docker, using %s as base url", updated)
        base_url = updated
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

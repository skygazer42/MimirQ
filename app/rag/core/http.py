"""
HTTP client helpers shared across RAG modules.

We centralize proxy environment handling here to avoid duplicating logic across
engine / rerankers / embedding clients.
"""


import logging
import os
from typing import Iterable, Optional

DEFAULT_PROXY_ENV_KEYS: tuple[str, ...] = (
    "OPENAI_PROXY",
    "HTTPS_PROXY",
    "HTTP_PROXY",
    "ALL_PROXY",
    "https_proxy",
    "http_proxy",
    "all_proxy",
)


def httpx_trust_env(
    *,
    proxy_env_keys: Iterable[str] = DEFAULT_PROXY_ENV_KEYS,
    logger: Optional[logging.Logger] = None,
) -> bool:
    """
    Decide whether httpx should trust environment proxy variables.

    Some environments set SOCKS proxies in env vars; httpx' SOCKS support needs
    extra dependencies. In that case we disable `trust_env` to avoid runtime
    errors and proxy misconfiguration.
    """
    proxies = [os.getenv(k) for k in proxy_env_keys]
    proxies = [p for p in proxies if p]
    socks_proxy = next((p for p in proxies if p.lower().startswith("socks")), None)
    if socks_proxy:
        if logger:
            logger.warning("Unsupported SOCKS proxy detected: %s. Ignoring env proxies.", socks_proxy)
        return False
    return True


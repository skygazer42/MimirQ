"""
HTTP environment helpers.

We keep this in app.core (not app.rag) so core modules can use it without
importing the whole RAG package (which has heavier imports and may create
cycles).
"""


import logging
import os
from collections.abc import Iterable

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
    logger: logging.Logger | None = None,
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


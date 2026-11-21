"""
HTTP proxy environment policy shared by application clients and startup.
"""

import logging
import os
from collections.abc import Iterable

from app.infrastructure.env import parse_csv

DEFAULT_PROXY_ENV_KEYS: tuple[str, ...] = (
    "OPENAI_PROXY",
    "HTTPS_PROXY",
    "HTTP_PROXY",
    "ALL_PROXY",
    "https_proxy",
    "http_proxy",
    "all_proxy",
)

LOCAL_NO_PROXY_HOSTS = ("localhost", "127.0.0.1", "::1")


def _merge_no_proxy_entries(current: str, hosts: Iterable[str]) -> str:
    entries = parse_csv(current)
    seen = set(entries)
    for host in hosts:
        clean = host.strip()
        if clean and clean not in seen:
            entries.append(clean)
            seen.add(clean)
    return ",".join(entries)


def ensure_local_no_proxy(hosts: Iterable[str] = LOCAL_NO_PROXY_HOSTS) -> None:
    """Keep local infrastructure calls out of global HTTP/SOCKS proxies."""
    host_list = tuple(hosts)
    for env_name in ("NO_PROXY", "no_proxy"):
        os.environ[env_name] = _merge_no_proxy_entries(os.getenv(env_name, ""), host_list)


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
    for key in proxy_env_keys:
        proxy = os.getenv(key, "")
        if proxy.lower().startswith("socks"):
            if logger is not None:
                logger.warning("Unsupported SOCKS proxy detected. Ignoring env proxies.")
            return False
    return True

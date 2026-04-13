from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit

DOCKER_LOCALHOST_FALLBACK = "127.0.0.1"


def build_docker_service_url_candidates(raw_url: str, *, service_hostnames: set[str]) -> list[str]:
    """
    Build candidate URLs for parser sidecars.

    Some heavyweight parser containers are easiest to colocate with the backend
    by sharing the backend container's network namespace. In that setup,
    dockerized backend code should call them through `127.0.0.1:<same-port>`.
    """
    raw = (raw_url or "").strip()
    if not raw:
        return []

    candidates: list[str] = [raw]
    try:
        parts = urlsplit(raw)
    except Exception:
        return candidates

    hostname = (parts.hostname or "").strip().lower()
    if hostname not in {name.strip().lower() for name in service_hostnames if name.strip()}:
        return candidates

    gateway_netloc = DOCKER_LOCALHOST_FALLBACK
    if parts.port:
        gateway_netloc = f"{gateway_netloc}:{parts.port}"
    fallback = urlunsplit((parts.scheme, gateway_netloc, parts.path, parts.query, parts.fragment))
    if fallback and fallback not in candidates:
        candidates.append(fallback)
    return candidates

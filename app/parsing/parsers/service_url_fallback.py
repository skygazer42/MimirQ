from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit

DOCKER_LOCALHOST_FALLBACK = "127.0.0.1"
LOCALHOST_NAMES = {"127.0.0.1", "localhost"}


def build_docker_service_url_candidates(raw_url: str, *, service_hostnames: set[str]) -> list[str]:
    """
    Build candidate URLs for parser sidecars.

    Parser sidecars have used two deployment shapes:
    - separate containers on the compose network, reachable by service hostname;
    - containers sharing the API network namespace, reachable by 127.0.0.1.

    Keep both candidates so an env file from one shape does not silently break
    the other during Docker rebuild/restart workflows.
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
    normalized_services = sorted({name.strip().lower() for name in service_hostnames if name.strip()})
    if not normalized_services:
        return candidates

    def _append_candidate(netloc_host: str) -> None:
        netloc = netloc_host
        if parts.port:
            netloc = f"{netloc}:{parts.port}"
        fallback = urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))
        if fallback and fallback not in candidates:
            candidates.append(fallback)

    if hostname in normalized_services:
        _append_candidate(DOCKER_LOCALHOST_FALLBACK)
    elif hostname in LOCALHOST_NAMES:
        for service in normalized_services:
            _append_candidate(service)
    return candidates

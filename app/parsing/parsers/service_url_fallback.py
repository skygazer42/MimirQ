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
    raw = raw_url.strip()
    if not raw:
        return []

    candidates: list[str] = [raw]
    try:
        parts = urlsplit(raw)
    except ValueError:
        return candidates

    hostname = parts.hostname.strip().lower() if parts.hostname is not None else None
    normalized_services = sorted({name.strip().lower() for name in service_hostnames if name.strip()})
    if not normalized_services:
        return candidates

    if hostname in normalized_services:
        alternative_hosts = [DOCKER_LOCALHOST_FALLBACK]
    elif hostname in LOCALHOST_NAMES:
        alternative_hosts = normalized_services
    else:
        return candidates

    for netloc_host in alternative_hosts:
        netloc = netloc_host
        if parts.port is not None:
            netloc = f"{netloc}:{parts.port}"
        fallback = urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))
        if fallback and fallback not in candidates:
            candidates.append(fallback)

    return candidates

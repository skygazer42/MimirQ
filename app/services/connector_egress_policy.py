import ipaddress
import socket
from collections.abc import Iterable

from app.core.config import settings

_WELL_KNOWN_METADATA_NETWORKS = (
    ipaddress.ip_network("169.254.169.254/32"),
    ipaddress.ip_network("100.100.100.200/32"),
    ipaddress.ip_network("192.0.0.192/32"),
    ipaddress.ip_network("fd00:ec2::254/128"),
)


def _split_cidr_tokens(raw: str | None) -> list[str]:
    text = str(raw or "").replace(",", " ")
    return [token.strip() for token in text.split() if token.strip()]


def _parse_allow_networks(raw: str | None) -> tuple[ipaddress._BaseNetwork, ...]:
    networks: list[ipaddress._BaseNetwork] = []
    for token in _split_cidr_tokens(raw):
        try:
            networks.append(ipaddress.ip_network(token, strict=False))
        except ValueError as exc:
            raise ValueError(f"Invalid connector DB egress allowlist CIDR: {token}") from exc
    return tuple(networks)


def _normalize_ip_literal(value: str) -> ipaddress._BaseAddress | None:
    candidate = str(value or "").strip()
    if candidate.startswith("[") and candidate.endswith("]"):
        candidate = candidate[1:-1].strip()
    try:
        return ipaddress.ip_address(candidate)
    except ValueError:
        return None


def _resolved_addresses(host: str) -> list[str]:
    ip_literal = _normalize_ip_literal(host)
    if ip_literal is not None:
        return [str(ip_literal)]

    resolved: list[str] = []
    seen: set[str] = set()
    for row in socket.getaddrinfo(host, None, type=socket.SOCK_STREAM):
        sockaddr = row[4]
        if not isinstance(sockaddr, tuple) or not sockaddr:
            continue
        address = str(sockaddr[0] or "").strip()
        if not address or address in seen:
            continue
        seen.add(address)
        resolved.append(address)
    if not resolved:
        raise ValueError(f"DB host {host!r} did not resolve to any addresses")
    return resolved


def _classify_blocked_address(address: ipaddress._BaseAddress) -> str | None:
    if any(address in network for network in _WELL_KNOWN_METADATA_NETWORKS):
        return "metadata"
    if address.is_unspecified:
        return "unspecified"
    if address.is_loopback:
        return "loopback"
    if address.is_link_local:
        return "link-local"
    if address.is_multicast:
        return "multicast"
    if address.is_private:
        return "private"
    return None


def _address_allowed(address: ipaddress._BaseAddress, allow_networks: Iterable[ipaddress._BaseNetwork]) -> bool:
    return any(address in network for network in allow_networks)


def validate_db_connector_destination(host: str, *, allow_cidrs: str | None = None) -> list[str]:
    normalized_host = str(host or "").strip()
    if not normalized_host:
        raise ValueError("DB host is required")

    configured_allowlist = settings.CONNECTOR_DB_EGRESS_ALLOW_CIDRS if allow_cidrs is None else allow_cidrs
    allow_networks = _parse_allow_networks(configured_allowlist)
    resolved = _resolved_addresses(normalized_host)

    for raw_address in resolved:
        address = ipaddress.ip_address(raw_address)
        if _address_allowed(address, allow_networks):
            continue
        blocked_class = _classify_blocked_address(address)
        if blocked_class is None:
            continue
        raise ValueError(
            f"DB host {normalized_host!r} resolved to blocked {blocked_class} address {raw_address}. "
            "Set CONNECTOR_DB_EGRESS_ALLOW_CIDRS to explicitly allow this destination."
        )

    return resolved


def validate_db_connector_config(config: dict | object) -> list[str]:
    host = ""
    if isinstance(config, dict):
        host = str(config.get("host") or "").strip()
    else:
        host = str(getattr(config, "host", "") or "").strip()
    return validate_db_connector_destination(host)

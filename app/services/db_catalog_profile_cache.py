"""
DB catalog profile cache.

Cache keying is intentionally explicit so callers can avoid re-querying the
database (or an external DB) for repeated "profile portrait" reads.

Key components (per project guidance):
- entitlement_hash
- table_fingerprint
- profile_version
"""


import time
from typing import Any

_CACHE_MAX_ENTRIES = 2048
_cache: dict[str, tuple[float, dict[str, Any]]] = {}


def build_db_profile_cache_key(
    *,
    tenant_id: str,
    dataset_id: str,
    entitlement_hash: str,
    table_fingerprint: str,
    profile_version: int,
) -> str:
    return f"db_profile:v{int(profile_version)}:{str(tenant_id)}:{str(dataset_id)}:{str(entitlement_hash)}:{str(table_fingerprint)}"


def get_cached_db_profile(key: str, *, ttl_sec: float) -> dict[str, Any] | None:
    ttl = float(ttl_sec or 0.0)
    if ttl <= 0:
        return None

    cached = _cache.get(str(key))
    if cached is None:
        return None

    ts, payload = cached
    if (time.monotonic() - float(ts)) > ttl:
        _cache.pop(str(key), None)
        return None

    return dict(payload)


def set_cached_db_profile(key: str, payload: dict[str, Any]) -> None:
    if len(_cache) > _CACHE_MAX_ENTRIES:
        _cache.clear()
    _cache[str(key)] = (time.monotonic(), dict(payload or {}))


"""
JWT verification helpers.

Supports:
- HS* algorithms using settings.SECRET_KEY (+ SECRET_KEY_FALLBACKS for rotation)
- RS*/ES* algorithms using a remote JWKS endpoint (settings.JWT_JWKS_URLS)

This module is intentionally best-effort:
- JWKS is cached in-memory with TTL to avoid fetching on every request
- On refresh failures, cached keys may be used for a bounded stale window
- Optional OIDC discovery can derive jwks_uri from JWT_ISSUER
"""


import asyncio
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx
from jose import ExpiredSignatureError, JWTError, jwt

from app.core.config import settings
from app.core.utils import parse_csv
from app.rag.core.logging import get_logger

logger = get_logger("core.jwt_verify")


def jwt_secret_key_candidates() -> list[str]:
    """
    Return candidate SECRET_KEY values for verifying JWTs.

    - settings.SECRET_KEY is always tried first
    - settings.SECRET_KEY_FALLBACKS can include previous keys (comma-separated)
    """
    current = str(getattr(settings, "SECRET_KEY", "") or "").strip()
    out: list[str] = [current] if current else []

    raw_fallbacks = str(getattr(settings, "SECRET_KEY_FALLBACKS", "") or "").strip()
    if not raw_fallbacks:
        return out

    for item in raw_fallbacks.split(","):
        key = str(item or "").strip()
        if not key or key == current:
            continue
        out.append(key)
        # Keep bounded to avoid pathological configs.
        if len(out) >= 6:
            break
    return out


@dataclass(frozen=True)
class _JWKSCacheEntry:
    keys: list[dict[str, Any]]
    fetched_at_monotonic: float
    expires_at_monotonic: float


_jwks_cache: dict[str, _JWKSCacheEntry] = {}
_jwks_locks: dict[str, asyncio.Lock] = {}

@dataclass(frozen=True)
class _OIDCDiscoveryEntry:
    jwks_uri: str
    fetched_at_monotonic: float
    expires_at_monotonic: float


_oidc_cache: dict[str, _OIDCDiscoveryEntry] = {}
_oidc_locks: dict[str, asyncio.Lock] = {}


def _jwks_lock(url: str) -> asyncio.Lock:
    lock = _jwks_locks.get(url)
    if lock is None:
        lock = asyncio.Lock()
        _jwks_locks[url] = lock
    return lock


def _oidc_lock(issuer: str) -> asyncio.Lock:
    lock = _oidc_locks.get(issuer)
    if lock is None:
        lock = asyncio.Lock()
        _oidc_locks[issuer] = lock
    return lock


def _oidc_config_url_for_issuer(issuer: str) -> str | None:
    raw = str(issuer or "").strip()
    if not raw:
        return None
    base = raw.rstrip("/")
    parsed = urlparse(base)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return f"{base}/.well-known/openid-configuration"


async def _fetch_oidc_configuration(url: str) -> dict[str, Any]:
    timeout_sec = float(getattr(settings, "JWT_OIDC_DISCOVERY_HTTP_TIMEOUT_SEC", 5.0) or 5.0)
    timeout = httpx.Timeout(timeout_sec)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, trust_env=True) as client:
        res = await client.get(str(url))
        res.raise_for_status()
        data = res.json()
    if not isinstance(data, dict):
        raise ValueError("invalid_oidc_configuration")
    return data


async def _get_oidc_jwks_uri(issuer: str, *, force_refresh: bool = False) -> str | None:
    ttl_sec = float(getattr(settings, "JWT_OIDC_DISCOVERY_CACHE_TTL_SEC", 3600) or 3600)
    max_stale_sec = float(getattr(settings, "JWT_OIDC_DISCOVERY_MAX_STALE_SEC", 86400) or 86400)

    issuer = str(issuer or "").strip()
    if not issuer:
        return None

    now = time.monotonic()
    cached = _oidc_cache.get(issuer)
    if cached and not force_refresh and now < cached.expires_at_monotonic:
        return str(cached.jwks_uri)

    lock = _oidc_lock(issuer)
    async with lock:
        now = time.monotonic()
        cached = _oidc_cache.get(issuer)
        if cached and not force_refresh and now < cached.expires_at_monotonic:
            return str(cached.jwks_uri)

        config_url = _oidc_config_url_for_issuer(issuer)
        if not config_url:
            return None

        try:
            cfg = await _fetch_oidc_configuration(config_url)
            jwks_uri = str(cfg.get("jwks_uri") or "").strip()
            parsed = urlparse(jwks_uri) if jwks_uri else None
            if not jwks_uri or parsed is None or parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValueError("invalid_oidc_jwks_uri")
        except Exception as exc:  # noqa: BLE001
            if cached and (now - cached.fetched_at_monotonic) <= max_stale_sec:
                logger.warning(
                    "OIDC discovery refresh failed for %s; using cached jwks_uri (age=%.0fs): %s",
                    issuer,
                    now - cached.fetched_at_monotonic,
                    str(exc)[:200],
                )
                return str(cached.jwks_uri)
            raise

        expires_at = now + max(1.0, ttl_sec)
        _oidc_cache[issuer] = _OIDCDiscoveryEntry(
            jwks_uri=jwks_uri,
            fetched_at_monotonic=now,
            expires_at_monotonic=expires_at,
        )
        return jwks_uri


async def _fetch_jwks_keys(url: str) -> list[dict[str, Any]]:
    """
    Fetch JWKS from the given URL and return its "keys" list.

    Note: this intentionally does NOT reuse the global HTTP client pool to avoid
    propagating internal X-Request-ID/X-Tenant-ID headers to external IdPs.
    """
    timeout_sec = float(getattr(settings, "JWT_JWKS_HTTP_TIMEOUT_SEC", 5.0) or 5.0)
    timeout = httpx.Timeout(timeout_sec)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, trust_env=True) as client:
        res = await client.get(str(url))
        res.raise_for_status()
        data = res.json()

    keys = data.get("keys") if isinstance(data, dict) else None
    if not isinstance(keys, list):
        raise ValueError("invalid_jwks_response")

    out: list[dict[str, Any]] = []
    for item in keys:
        if isinstance(item, dict):
            out.append(item)
    if not out:
        raise ValueError("empty_jwks_keys")
    return out


async def _get_jwks_keys(url: str, *, force_refresh: bool = False) -> list[dict[str, Any]]:
    ttl_sec = float(getattr(settings, "JWT_JWKS_CACHE_TTL_SEC", 300) or 300)
    max_stale_sec = float(getattr(settings, "JWT_JWKS_MAX_STALE_SEC", 3600) or 3600)

    now = time.monotonic()
    cached = _jwks_cache.get(url)
    if cached and not force_refresh and now < cached.expires_at_monotonic:
        return list(cached.keys)

    lock = _jwks_lock(url)
    async with lock:
        now = time.monotonic()
        cached = _jwks_cache.get(url)
        if cached and not force_refresh and now < cached.expires_at_monotonic:
            return list(cached.keys)

        try:
            keys = await _fetch_jwks_keys(url)
        except Exception as exc:  # noqa: BLE001
            if cached and (now - cached.fetched_at_monotonic) <= max_stale_sec:
                logger.warning(
                    "JWKS refresh failed for %s; using cached keys (age=%.0fs): %s",
                    str(url),
                    now - cached.fetched_at_monotonic,
                    str(exc)[:200],
                )
                return list(cached.keys)
            raise

        expires_at = now + max(1.0, ttl_sec)
        _jwks_cache[url] = _JWKSCacheEntry(keys=list(keys), fetched_at_monotonic=now, expires_at_monotonic=expires_at)
        return list(keys)


def _find_jwk_for_kid(keys: list[dict[str, Any]], kid: str | None) -> dict[str, Any] | None:
    if not keys:
        return None
    if kid:
        wanted = str(kid).strip()
        for key in keys:
            if str(key.get("kid") or "").strip() == wanted:
                return key
        return None

    # No kid: only safe to auto-select when unambiguous.
    if len(keys) == 1:
        return keys[0]
    return None


async def _jwks_key_for_token(token: str) -> dict[str, Any]:
    urls = parse_csv(str(getattr(settings, "JWT_JWKS_URLS", "") or ""))
    if not urls and bool(getattr(settings, "JWT_JWKS_DISCOVERY_ENABLED", False)):
        issuer = str(getattr(settings, "JWT_ISSUER", "") or "").strip()
        jwks_uri = await _get_oidc_jwks_uri(issuer)
        urls = [jwks_uri] if jwks_uri else []
    if not urls:
        raise JWTError("JWKS not configured")

    header = jwt.get_unverified_header(token)
    kid = str(header.get("kid") or "").strip() or None

    last_exc: Exception | None = None
    for url in urls:
        try:
            keys = await _get_jwks_keys(url)
            found = _find_jwk_for_kid(keys, kid)
            if found:
                return found

            # Key rotation: refresh once on kid miss.
            keys = await _get_jwks_keys(url, force_refresh=True)
            found = _find_jwk_for_kid(keys, kid)
            if found:
                return found
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            continue

    raise JWTError("Unable to find a signing key") from last_exc


async def decode_access_token(token: str) -> dict:
    """
    Decode and verify an access token according to configured auth settings.

    Raises jose.JWTError / jose.ExpiredSignatureError on verification failures.
    """
    algorithm = str(getattr(settings, "ALGORITHM", "HS256") or "HS256").strip() or "HS256"
    algorithms = [algorithm]
    issuer = str(getattr(settings, "JWT_ISSUER", "") or "").strip()
    audience = str(getattr(settings, "JWT_AUDIENCE", "") or "").strip()

    decode_kwargs: dict = {
        "algorithms": algorithms,
        "options": {"verify_exp": True},
    }
    if issuer:
        decode_kwargs["issuer"] = issuer
    if audience:
        decode_kwargs["audience"] = audience

    if algorithm.upper().startswith("HS"):
        last_exc: Exception | None = None
        for secret_key in jwt_secret_key_candidates():
            try:
                return jwt.decode(token, secret_key, **decode_kwargs)
            except ExpiredSignatureError:
                # ExpiredSignatureError implies signature validation succeeded; do not try other keys.
                raise
            except JWTError as exc:
                last_exc = exc
                continue
        raise JWTError("Signature verification failed") from last_exc

    jwk_key = await _jwks_key_for_token(token)
    return jwt.decode(token, jwk_key, **decode_kwargs)

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
from urllib.parse import urlparse, urlunparse

import httpx
import jwt
from jwt import ExpiredSignatureError, InvalidTokenError, PyJWK

from app.core.config import settings, validate_jwt_remote_url
from app.core.utils import parse_csv
from app.rag.core.logging import get_logger

logger = get_logger("core.jwt_verify")


def _validate_response_url_chain(*, requested_url: str, response: httpx.Response, error_name: str) -> None:
    requested = (requested_url).strip()
    response_urls = [str(item.url) for item in response.history]
    response_urls.append(str(response.url))
    if not response_urls[-1]:
        raise ValueError(error_name)

    requested_scheme = (urlparse(requested).scheme).strip().lower()
    for response_url in response_urls:
        if requested_scheme == "https" and (urlparse(response_url).scheme).lower() != "https":
            raise ValueError(error_name)
        try:
            validate_jwt_remote_url(response_url, field_name="JWT_REMOTE_RESPONSE_URL")
        except ValueError as exc:
            raise ValueError(error_name) from exc


def jwt_secret_key_candidates() -> list[str]:
    """
    Return candidate SECRET_KEY values for verifying JWTs.

    - settings.SECRET_KEY is always tried first
    - settings.SECRET_KEY_FALLBACKS can include previous keys (comma-separated)
    """
    current = (settings.SECRET_KEY).strip()
    out: list[str] = [current] if current else []

    raw_fallbacks = (settings.SECRET_KEY_FALLBACKS).strip()
    if not raw_fallbacks:
        return out

    for item in raw_fallbacks.split(","):
        key = (item).strip()
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
    raw = (issuer).strip()
    if not raw:
        return None
    base = raw.rstrip("/")
    parsed = urlparse(base)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return f"{base}/.well-known/openid-configuration"


def _normalize_oidc_issuer(raw_issuer: str) -> str:
    raw = (raw_issuer).strip()
    if not raw:
        return ""
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return ""
    host = parsed.hostname.lower()
    if parsed.port:
        host = f"{host}:{parsed.port}"
    return urlunparse(
        (
            parsed.scheme.lower(),
            host,
            (parsed.path).rstrip("/"),
            "",
            "",
            "",
        )
    )


async def _fetch_oidc_configuration(url: str) -> dict[str, Any]:
    timeout_sec = float(settings.JWT_OIDC_DISCOVERY_HTTP_TIMEOUT_SEC or 5.0)
    timeout = httpx.Timeout(timeout_sec)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, trust_env=True) as client:
        res = await client.get(url)
        res.raise_for_status()
        _validate_response_url_chain(
            requested_url=url,
            response=res,
            error_name="insecure_oidc_discovery_url",
        )
        data = res.json()
    if not isinstance(data, dict):
        raise ValueError("invalid_oidc_configuration")
    return data


async def _get_oidc_jwks_uri(issuer: str, *, force_refresh: bool = False) -> str | None:
    ttl_sec = float(settings.JWT_OIDC_DISCOVERY_CACHE_TTL_SEC or 3600)
    max_stale_sec = float(settings.JWT_OIDC_DISCOVERY_MAX_STALE_SEC or 86400)

    issuer = (issuer).strip()
    if not issuer:
        return None

    now = time.monotonic()
    cached = _oidc_cache.get(issuer)
    if cached and not force_refresh and now < cached.expires_at_monotonic:
        return cached.jwks_uri

    lock = _oidc_lock(issuer)
    async with lock:
        now = time.monotonic()
        cached = _oidc_cache.get(issuer)
        if cached and not force_refresh and now < cached.expires_at_monotonic:
            return cached.jwks_uri

        config_url = _oidc_config_url_for_issuer(issuer)
        if not config_url:
            return None

        try:
            cfg = await _fetch_oidc_configuration(config_url)
            configured_issuer = _normalize_oidc_issuer(issuer)
            discovered_issuer = _normalize_oidc_issuer(cfg["issuer"])
            if configured_issuer and discovered_issuer != configured_issuer:
                raise ValueError("invalid_oidc_issuer_mismatch")
            jwks_uri = cfg["jwks_uri"].strip()
            try:
                validate_jwt_remote_url(jwks_uri, field_name="OIDC discovery jwks_uri")
            except ValueError as exc:
                raise ValueError("invalid_oidc_jwks_uri") from exc
            if not jwks_uri:
                raise ValueError("invalid_oidc_jwks_uri")
        except Exception as exc:  # noqa: BLE001
            if cached and (now - cached.fetched_at_monotonic) <= max_stale_sec:
                logger.warning(
                    "OIDC discovery refresh failed for %s; using cached jwks_uri (age=%.0fs): %s",
                    issuer,
                    now - cached.fetched_at_monotonic,
                    str(exc)[:200],
                )
                return cached.jwks_uri
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
    timeout_sec = float(settings.JWT_JWKS_HTTP_TIMEOUT_SEC or 5.0)
    timeout = httpx.Timeout(timeout_sec)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, trust_env=True) as client:
        res = await client.get(url)
        res.raise_for_status()
        _validate_response_url_chain(
            requested_url=url,
            response=res,
            error_name="insecure_jwks_response_url",
        )
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
    ttl_sec = float(settings.JWT_JWKS_CACHE_TTL_SEC or 300)
    max_stale_sec = float(settings.JWT_JWKS_MAX_STALE_SEC or 3600)

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
                    url,
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
        wanted = kid.strip()
        for key in keys:
            key_id = key.get("kid")
            if isinstance(key_id, str) and key_id.strip() == wanted:
                return key
        return None

    # No kid: only safe to auto-select when unambiguous.
    if len(keys) == 1:
        return keys[0]
    return None


async def _jwks_key_for_token(token: str) -> dict[str, Any]:
    urls = parse_csv(settings.JWT_JWKS_URLS)
    if not urls and settings.JWT_JWKS_DISCOVERY_ENABLED:
        issuer = (settings.JWT_ISSUER).strip()
        jwks_uri = await _get_oidc_jwks_uri(issuer)
        urls = [jwks_uri] if jwks_uri else []
    if not urls:
        raise InvalidTokenError("JWKS not configured")

    header = jwt.get_unverified_header(token)
    kid = header.get("kid")
    if kid is not None:
        kid = kid.strip()

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

    raise InvalidTokenError("Unable to find a signing key") from last_exc


async def decode_access_token(token: str) -> dict[str, Any]:
    """
    Decode and verify an access token according to configured auth settings.

    Raises jwt.InvalidTokenError / jwt.ExpiredSignatureError on verification failures.
    """
    algorithm = (settings.ALGORITHM or "HS256").strip() or "HS256"
    algorithms = [algorithm]
    issuer = (settings.JWT_ISSUER).strip()
    audience = (settings.JWT_AUDIENCE).strip()

    decode_kwargs: dict[str, Any] = {
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
            except InvalidTokenError as exc:
                last_exc = exc
                continue
        raise InvalidTokenError("Signature verification failed") from last_exc

    jwk_key = await _jwks_key_for_token(token)
    try:
        signing_key = PyJWK.from_dict(jwk_key)
    except Exception as exc:  # noqa: BLE001
        # Malformed JWKS entries must surface as token verification failures (401), not 500s.
        raise InvalidTokenError("Invalid JWKS signing key") from exc
    return jwt.decode(token, signing_key, **decode_kwargs)

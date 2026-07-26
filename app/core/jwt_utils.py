"""
JWT helpers for issuing access tokens.
"""
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt

from app.core.config import settings


def _normalize_claim_key(value: Any) -> str:
    return str(value or "").strip()


def _merge_extra_claims(payload: dict[str, Any], extra_claims: dict[str, Any] | None) -> None:
    if not extra_claims:
        return
    for key, claim_value in dict(extra_claims).items():
        claim_key = _normalize_claim_key(key)
        if not claim_key or claim_key in payload:
            continue
        payload[claim_key] = claim_value


def _set_string_claim(payload: dict[str, Any], key: Any, value: Any) -> None:
    claim_key = _normalize_claim_key(key)
    if not claim_key:
        return
    claim_value = str(value or "").strip()
    if claim_value:
        payload[claim_key] = claim_value


def create_access_token(
    subject: str,
    *,
    expires_minutes: int | None = None,
    tenant_id: str | None = None,
    extra_claims: dict[str, Any] | None = None,
) -> tuple[str, int]:
    """
    Create a signed JWT access token.

    Returns (token, expires_in_seconds).
    """
    minutes = int(expires_minutes or getattr(settings, "ACCESS_TOKEN_EXPIRE_MINUTES", 30))
    expires_delta = timedelta(minutes=max(1, minutes))
    now = datetime.now(UTC)
    expire_at = now + expires_delta
    payload = {
        "sub": str(subject),
        "exp": expire_at,
        "iat": now,
    }
    _merge_extra_claims(payload, extra_claims)
    _set_string_claim(payload, "iss", getattr(settings, "JWT_ISSUER", ""))
    _set_string_claim(payload, "aud", getattr(settings, "JWT_AUDIENCE", ""))
    _set_string_claim(payload, getattr(settings, "JWT_TENANT_CLAIM", ""), tenant_id)
    token = jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return token, int(expires_delta.total_seconds())

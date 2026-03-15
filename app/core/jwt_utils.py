"""
JWT helpers for issuing access tokens.
"""
from datetime import UTC, datetime, timedelta
from typing import Any

from jose import jwt

from app.core.config import settings


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
    expire_at = datetime.now(UTC) + expires_delta
    payload = {
        "sub": str(subject),
        "exp": expire_at,
        "iat": datetime.now(UTC),
    }
    if extra_claims:
        for key, value in dict(extra_claims).items():
            k = str(key or "").strip()
            if not k or k in payload:
                continue
            payload[k] = value
    issuer = str(getattr(settings, "JWT_ISSUER", "") or "").strip()
    if issuer:
        payload["iss"] = issuer
    audience = str(getattr(settings, "JWT_AUDIENCE", "") or "").strip()
    if audience:
        payload["aud"] = audience
    tenant_claim = str(getattr(settings, "JWT_TENANT_CLAIM", "") or "").strip()
    if tenant_claim and tenant_id:
        payload[tenant_claim] = str(tenant_id).strip()
    token = jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return token, int(expires_delta.total_seconds())

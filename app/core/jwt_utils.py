"""
JWT helpers for issuing access tokens.
"""
from datetime import datetime, timedelta, timezone
from typing import Tuple

from jose import jwt

from app.core.config import settings


def create_access_token(subject: str, *, expires_minutes: int | None = None) -> Tuple[str, int]:
    """
    Create a signed JWT access token.

    Returns (token, expires_in_seconds).
    """
    minutes = int(expires_minutes or getattr(settings, "ACCESS_TOKEN_EXPIRE_MINUTES", 30))
    expires_delta = timedelta(minutes=max(1, minutes))
    expire_at = datetime.now(timezone.utc) + expires_delta
    payload = {
        "sub": str(subject),
        "exp": expire_at,
        "iat": datetime.now(timezone.utc),
    }
    issuer = str(getattr(settings, "JWT_ISSUER", "") or "").strip()
    if issuer:
        payload["iss"] = issuer
    audience = str(getattr(settings, "JWT_AUDIENCE", "") or "").strip()
    if audience:
        payload["aud"] = audience
    token = jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return token, int(expires_delta.total_seconds())

"""
Authentication dependency.

Parses user identity from request headers.
"""

import logging

from fastapi import Header, HTTPException
from jose import ExpiredSignatureError, JWTError, jwt

from app.core.config import settings

logger = logging.getLogger(__name__)


def get_current_account_id(
    authorization: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
) -> str:
    """
    Resolve current account id from request headers.

    - AUTH_MODE=jwt: require Authorization: Bearer <token> and validate JWT.
    - AUTH_MODE=header (local/dev default): require X-User-ID header (unsafe; forbidden in production).
    """
    mode = (getattr(settings, "AUTH_MODE", "jwt") or "jwt").lower()

    if mode == "header":
        if not x_user_id:
            raise HTTPException(status_code=401, detail="X-User-ID header required")
        return str(x_user_id)

    if not authorization:
        raise HTTPException(status_code=401, detail="Authorization header required")

    token = authorization.strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    else:
        raise HTTPException(status_code=401, detail="Invalid Authorization header")

    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM],
            options={"verify_exp": True}  # Explicitly enable expiration checks.
        )
    except ExpiredSignatureError as exc:
        logger.warning("Expired token attempted for access")
        raise HTTPException(status_code=401, detail="Token expired") from exc
    except JWTError as exc:
        logger.warning("Invalid token: %s", str(exc)[:100])
        raise HTTPException(status_code=401, detail="Invalid token") from exc

    user_id = payload.get("sub")
    if not user_id:
        logger.warning("Token missing 'sub' claim")
        raise HTTPException(status_code=401, detail="Invalid token")

    return str(user_id)

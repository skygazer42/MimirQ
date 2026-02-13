"""
Authentication dependency.

Parses user identity from request headers.
"""

import logging

from fastapi import Header, HTTPException
from jose import ExpiredSignatureError, JWTError, jwt

from app.core.config import settings
from app.core.logging_config import set_request_user_id

logger = logging.getLogger(__name__)


def _jwt_secret_key_candidates() -> list[str]:
    """
    Return candidate SECRET_KEY values for verifying JWTs.

    - settings.SECRET_KEY is always tried first
    - settings.SECRET_KEY_FALLBACKS can include previous keys (comma-separated)

    This enables key rotation without immediately invalidating still-valid tokens.
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


def _decode_access_token(token: str) -> dict:
    algorithms = [str(getattr(settings, "ALGORITHM", "HS256") or "HS256").strip() or "HS256"]
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

    last_exc: Exception | None = None
    for secret_key in _jwt_secret_key_candidates():
        try:
            return jwt.decode(token, secret_key, **decode_kwargs)
        except ExpiredSignatureError:
            # ExpiredSignatureError implies signature validation succeeded; do not try other keys.
            raise
        except JWTError as exc:
            last_exc = exc
            continue

    raise JWTError("Signature verification failed") from last_exc


def get_current_account_id_from_headers(*, authorization: str | None, x_user_id: str | None) -> str:
    """
    Resolve current account id from request headers.

    - AUTH_MODE=jwt: require Authorization: Bearer <token> and validate JWT.
    - AUTH_MODE=header (local/dev default): require X-User-ID header (unsafe; forbidden in production).
    """
    mode = (getattr(settings, "AUTH_MODE", "jwt") or "jwt").lower()

    if mode == "header":
        if not x_user_id:
            raise HTTPException(status_code=401, detail="X-User-ID header required")
        user_id = str(x_user_id)
        set_request_user_id(user_id)
        return user_id

    if not authorization:
        raise HTTPException(status_code=401, detail="Authorization header required")

    token = authorization.strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    else:
        raise HTTPException(status_code=401, detail="Invalid Authorization header")

    try:
        payload = _decode_access_token(token)
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

    user_id = str(user_id)
    set_request_user_id(user_id)
    return user_id


async def get_current_account_id(
    authorization: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
) -> str:
    """
    FastAPI dependency wrapper.

    Important: keep this async so it runs in the main request context (not a threadpool),
    allowing request-scoped contextvars (e.g. user_id) to propagate to sync endpoints.
    """
    return get_current_account_id_from_headers(authorization=authorization, x_user_id=x_user_id)

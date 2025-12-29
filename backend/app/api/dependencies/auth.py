"""
用户认证依赖

从请求头中解析用户身份信息。
"""

from fastapi import Header, HTTPException
from jose import JWTError, jwt

from app.core.config import settings


def get_current_account_id(
    authorization: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
) -> str:
    """
    Resolve current account id from request headers.

    - AUTH_MODE=jwt (default): require Authorization: Bearer <token> and validate JWT.
    - AUTH_MODE=header: require X-User-ID header (unsafe; intended for local/dev only).
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
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token")

    return str(user_id)

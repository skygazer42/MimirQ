"""
Simple auth dependency: extract user/account id from header.
"""

from fastapi import Header, HTTPException


def get_current_account_id(x_user_id: str | None = Header(default=None)) -> str:
    """
    Resolve current account id from header X-User-ID.
    """
    if not x_user_id:
        raise HTTPException(status_code=401, detail="X-User-ID header required")
    return x_user_id


"""
用户认证依赖

从请求头中解析用户身份信息。
"""

from fastapi import Header, HTTPException


def get_current_account_id(x_user_id: str | None = Header(default=None)) -> str:
    """
    从请求头 X-User-ID 中获取当前用户 ID。
    """
    if not x_user_id:
        raise HTTPException(status_code=401, detail="X-User-ID header required")
    return x_user_id


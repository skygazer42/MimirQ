"""
租户识别依赖

从请求头中解析租户 ID，支持默认值回退。
"""

from uuid import UUID
import os
from fastapi import Header, HTTPException
from app.core.config import settings

def get_tenant_id(x_tenant_id: str | None = Header(default=None)) -> UUID:
    """
    从请求头获取租户 ID，若未提供则使用默认值。
    """
    raw = x_tenant_id
    if not raw:
        is_production = os.getenv("ENV", "").lower() in ("prod", "production")
        if is_production:
            raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
        raw = settings.DEFAULT_TENANT_ID
    try:
        return UUID(str(raw))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid tenant id")

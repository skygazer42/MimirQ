"""
Tenant identification dependency.

Parses tenant ID from request headers with default value fallback.
"""

from uuid import UUID
import os
from fastapi import Header, HTTPException
from app.core.config import settings

def get_tenant_id(x_tenant_id: str | None = Header(default=None)) -> UUID:
    """
    Get tenant ID from request header, using default value if not provided.
    """
    raw = x_tenant_id
    if not raw:
        is_production = os.getenv("ENV", "").lower() in ("prod", "production")
        if is_production:
            raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
        raw = settings.DEFAULT_TENANT_ID
    try:
        return UUID(str(raw))
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid tenant id")

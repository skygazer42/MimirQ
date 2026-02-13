"""
Tenant identification dependency.

Parses tenant ID from request headers with default value fallback.
"""

from uuid import UUID

from fastapi import Header, HTTPException, Request

from app.core.config import settings
from app.core.env import is_production_env


def get_tenant_id(request: Request, x_tenant_id: str | None = Header(default=None)) -> UUID:
    """
    Get tenant ID from request header, using default value if not provided.
    """
    raw = (x_tenant_id or "").strip() or None
    tenant_header = str(getattr(settings, "TENANT_HEADER", "") or "X-Tenant-ID").strip() or "X-Tenant-ID"
    if not raw and tenant_header.lower() != "x-tenant-id":
        raw = (request.headers.get(tenant_header) or "").strip() or None
    if not raw:
        if is_production_env():
            raise HTTPException(status_code=400, detail=f"{tenant_header} header required")
        raw = settings.DEFAULT_TENANT_ID
    try:
        return UUID(str(raw))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid tenant id") from exc

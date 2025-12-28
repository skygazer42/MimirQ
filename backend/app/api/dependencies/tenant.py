
from uuid import UUID
from fastapi import Header, HTTPException
from app.core.config import settings

def get_tenant_id(x_tenant_id: str | None = Header(default=None)) -> UUID:
    """
    Resolve tenant id from header, fallback to default.
    """
    raw = x_tenant_id or settings.DEFAULT_TENANT_ID
    try:
        return UUID(str(raw))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid tenant id")


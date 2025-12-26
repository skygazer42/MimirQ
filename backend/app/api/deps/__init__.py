"""
FastAPI dependency helpers.

Keep request-scoped dependencies close to the API layer.
"""

from app.api.deps.auth import get_current_account_id
from app.api.deps.tenant import get_tenant_id

__all__ = ["get_current_account_id", "get_tenant_id"]

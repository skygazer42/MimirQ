"""
FastAPI dependency helpers.

Keep request-scoped dependencies close to the API layer.
"""

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id

__all__ = ["get_current_account_id", "get_tenant_id"]

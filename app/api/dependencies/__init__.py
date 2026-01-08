"""
FastAPI dependency injection module

Provides request-level dependency injection helper functions including:
- User authentication
- Tenant identification
"""

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id

__all__ = ["get_current_account_id", "get_tenant_id"]

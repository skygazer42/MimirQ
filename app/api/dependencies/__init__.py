"""
FastAPI 依赖注入模块

提供请求级别的依赖注入辅助函数，包括：
- 用户认证
- 租户识别
"""

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id

__all__ = ["get_current_account_id", "get_tenant_id"]

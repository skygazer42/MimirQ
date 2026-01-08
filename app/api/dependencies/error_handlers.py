"""
通用 API 错误处理工具

提供常用的资源验证和错误处理函数，消除 API 路由中的重复代码。
"""

from typing import Any, Type, TypeVar
from fastapi import HTTPException
from sqlalchemy.orm import Session



T = TypeVar("T")


def get_or_404(
    db: Session,
    model: Type[T],
    resource_name: str = None,
    **filters
) -> T:
    """
    获取资源或抛出 404 错误

    Args:
        db: 数据库会话
        model: SQLAlchemy 模型类
        resource_name: 资源名称（用于错误消息），默认使用模型类名
        **filters: 查询过滤条件

    Returns:
        查询到的资源

    Raises:
        HTTPException: 404 Not Found

    Example:
        dataset = get_or_404(db, Dataset, dataset_id=dataset_id, tenant_id=tenant_id)
    """
    resource_name = resource_name or model.__name__
    resource = db.query(model).filter_by(**filters).first()
    if not resource:
        raise HTTPException(status_code=404, detail=f"{resource_name} not found")
    return resource


def check_exists_or_404(
    resource: Any,
    resource_name: str = "Resource"
) -> None:
    """
    检查资源是否存在，不存在则抛出 404

    Args:
        resource: 要检查的资源
        resource_name: 资源名称

    Raises:
        HTTPException: 404 Not Found
    """
    if not resource:
        raise HTTPException(status_code=404, detail=f"{resource_name} not found")


def check_permission_or_403(
    condition: bool,
    message: str = "Permission denied"
) -> None:
    """
    检查权限，无权限则抛出 403

    Args:
        condition: 权限条件（True 表示有权限）
        message: 错误消息

    Raises:
        HTTPException: 403 Forbidden
    """
    if not condition:
        raise HTTPException(status_code=403, detail=message)


def check_member_or_403(
    db: Session,
    tenant_member_model: Type,
    tenant_id: Any,
    user_id: str,
    message: str = "Not a tenant member"
) -> Any:
    """
    检查用户是否是租户成员

    Args:
        db: 数据库会话
        tenant_member_model: TenantMember 模型类
        tenant_id: 租户 ID
        user_id: 用户 ID
        message: 错误消息

    Returns:
        成员记录

    Raises:
        HTTPException: 403 Forbidden
    """
    member = db.query(tenant_member_model).filter(
        tenant_member_model.tenant_id == tenant_id,
        tenant_member_model.user_id == user_id
    ).first()
    if not member:
        raise HTTPException(status_code=403, detail=message)
    return member


def validate_or_400(
    condition: bool,
    message: str = "Invalid request"
) -> None:
    """
    验证条件，不满足则抛出 400

    Args:
        condition: 验证条件（True 表示通过）
        message: 错误消息

    Raises:
        HTTPException: 400 Bad Request
    """
    if not condition:
        raise HTTPException(status_code=400, detail=message)


__all__ = [
    "get_or_404",
    "check_exists_or_404",
    "check_permission_or_403",
    "check_member_or_403",
    "validate_or_400",
]

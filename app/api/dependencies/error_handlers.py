"""
Common API error handling utilities

Provides commonly used resource validation and error handling functions to eliminate duplicate code in API routes.
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
    Get resource or raise 404 error

    Args:
        db: Database session
        model: SQLAlchemy model class
        resource_name: Resource name (for error message), defaults to model class name
        **filters: Query filter conditions

    Returns:
        The queried resource

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
    Check if resource exists, raise 404 if not

    Args:
        resource: Resource to check
        resource_name: Resource name

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
    Check permission, raise 403 if not authorized

    Args:
        condition: Permission condition (True means authorized)
        message: Error message

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
    Check if user is a tenant member

    Args:
        db: Database session
        tenant_member_model: TenantMember model class
        tenant_id: Tenant ID
        user_id: User ID
        message: Error message

    Returns:
        Member record

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
    Validate condition, raise 400 if not satisfied

    Args:
        condition: Validation condition (True means passed)
        message: Error message

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

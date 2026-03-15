"""
Service layer base class.

Provides common CRUD operations to reduce service duplication.
"""

from typing import Generic, TypeVar
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.constants import UserRoles
from app.models.tenant import TenantMember

# Generic type variable.
ModelType = TypeVar("ModelType")


# Roles allowed to edit.
EDIT_ROLES = UserRoles.EDIT_ROLES


class BaseService(Generic[ModelType]):
    """
    Service base class.

    Provides common CRUD operations and permission checks.

    Example:
        class DocumentService(BaseService[Document]):
            model = Document

            @classmethod
            def get_by_dataset(cls, db: Session, dataset_id: UUID) -> List[Document]:
                return db.query(cls.model).filter(cls.model.dataset_id == dataset_id).all()
    """

    model: type[ModelType] = None  # Subclasses must set.

    @classmethod
    def get_by_id(
        cls,
        db: Session,
        id: UUID,
        raise_404: bool = True
    ) -> ModelType | None:
        """
        Get resource by ID.

        Args:
            db: Database session.
            id: Resource ID.
            raise_404: Whether to raise 404 when not found.

        Returns:
            Resource or None.
        """
        resource = db.query(cls.model).filter(cls.model.id == id).first()
        if not resource and raise_404:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"{cls.model.__name__} not found"
            )
        return resource

    @classmethod
    def get_by_tenant(
        cls,
        db: Session,
        tenant_id: UUID,
        id: UUID,
        raise_404: bool = True
    ) -> ModelType | None:
        """
        Get resource by tenant ID and resource ID.

        Args:
            db: Database session.
            tenant_id: Tenant ID.
            id: Resource ID.
            raise_404: Whether to raise 404 when not found.

        Returns:
            Resource or None.
        """
        resource = db.query(cls.model).filter(
            cls.model.id == id,
            cls.model.tenant_id == tenant_id
        ).first()
        if not resource and raise_404:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"{cls.model.__name__} not found"
            )
        return resource

    @classmethod
    def list_by_tenant(
        cls,
        db: Session,
        tenant_id: UUID,
        skip: int = 0,
        limit: int = 50,
        **filters
    ) -> list[ModelType]:
        """
        List resources under a tenant.

        Args:
            db: Database session.
            tenant_id: Tenant ID.
            skip: Items to skip.
            limit: Items to return.
            **filters: Extra filters.

        Returns:
            Resource list.
        """
        query = db.query(cls.model).filter(cls.model.tenant_id == tenant_id)
        for key, value in filters.items():
            if value is not None and hasattr(cls.model, key):
                query = query.filter(getattr(cls.model, key) == value)
        return query.offset(skip).limit(limit).all()

    @classmethod
    def count_by_tenant(
        cls,
        db: Session,
        tenant_id: UUID,
        **filters
    ) -> int:
        """
        Get total resource count under a tenant.

        Args:
            db: Database session.
            tenant_id: Tenant ID.
            **filters: Extra filters.

        Returns:
            Total count.
        """
        query = db.query(cls.model).filter(cls.model.tenant_id == tenant_id)
        for key, value in filters.items():
            if value is not None and hasattr(cls.model, key):
                query = query.filter(getattr(cls.model, key) == value)
        return query.count()

    @classmethod
    def create(
        cls,
        db: Session,
        **kwargs
    ) -> ModelType:
        """
        Create resource.

        Args:
            db: Database session.
            **kwargs: Resource attributes.

        Returns:
            Created resource.
        """
        resource = cls.model(**kwargs)
        db.add(resource)
        db.commit()
        db.refresh(resource)
        return resource

    @classmethod
    def update(
        cls,
        db: Session,
        resource: ModelType,
        **kwargs
    ) -> ModelType:
        """
        Update resource.

        Args:
            db: Database session.
            resource: Resource object.
            **kwargs: Attributes to update.

        Returns:
            Updated resource.
        """
        for key, value in kwargs.items():
            if value is not None and hasattr(resource, key):
                setattr(resource, key, value)
        db.commit()
        db.refresh(resource)
        return resource

    @classmethod
    def delete(
        cls,
        db: Session,
        resource: ModelType
    ) -> None:
        """
        Delete resource.

        Args:
            db: Database session.
            resource: Resource object.
        """
        db.delete(resource)
        db.commit()

    @classmethod
    def ensure_member(
        cls,
        db: Session,
        tenant_id: UUID,
        account_id: str
    ) -> TenantMember:
        """
        Ensure user is a tenant member.

        Args:
            db: Database session.
            tenant_id: Tenant ID.
            account_id: User ID.

        Returns:
            Member record.

        Raises:
            HTTPException: 403 Forbidden.
        """
        member = db.query(TenantMember).filter(
            TenantMember.tenant_id == tenant_id,
            TenantMember.user_id == account_id
        ).first()
        if not member:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not a tenant member"
            )
        return member

    @classmethod
    def assert_edit_role(cls, member: TenantMember) -> None:
        """
        Ensure user has edit permissions.

        Args:
            member: Member record.

        Raises:
            HTTPException: 403 Forbidden.
        """
        role = (member.role or "").lower()
        if role not in EDIT_ROLES:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No permission to edit"
            )


__all__ = [
    "BaseService",
    "EDIT_ROLES",
]

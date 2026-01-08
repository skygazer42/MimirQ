"""
服务层基类

提供常用的数据库 CRUD 操作，减少服务层代码重复。
"""

from typing import Generic, List, Optional, Type, TypeVar
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.tenant import TenantMember


# 泛型类型变量
ModelType = TypeVar("ModelType")


# 允许编辑的角色
EDIT_ROLES = {"owner", "admin", "editor", "dataset_operator"}


class BaseService(Generic[ModelType]):
    """
    服务层基类

    提供常用的 CRUD 操作和权限检查方法。

    使用示例:
        class DocumentService(BaseService[Document]):
            model = Document

            @classmethod
            def get_by_dataset(cls, db: Session, dataset_id: UUID) -> List[Document]:
                return db.query(cls.model).filter(cls.model.dataset_id == dataset_id).all()
    """

    model: Type[ModelType] = None  # 子类必须设置

    @classmethod
    def get_by_id(
        cls,
        db: Session,
        id: UUID,
        raise_404: bool = True
    ) -> Optional[ModelType]:
        """
        根据 ID 获取资源

        Args:
            db: 数据库会话
            id: 资源 ID
            raise_404: 未找到时是否抛出 404 异常

        Returns:
            资源对象或 None
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
    ) -> Optional[ModelType]:
        """
        根据租户 ID 和资源 ID 获取资源

        Args:
            db: 数据库会话
            tenant_id: 租户 ID
            id: 资源 ID
            raise_404: 未找到时是否抛出 404 异常

        Returns:
            资源对象或 None
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
    ) -> List[ModelType]:
        """
        获取租户下的资源列表

        Args:
            db: 数据库会话
            tenant_id: 租户 ID
            skip: 跳过条数
            limit: 返回条数
            **filters: 额外过滤条件

        Returns:
            资源列表
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
        获取租户下的资源总数

        Args:
            db: 数据库会话
            tenant_id: 租户 ID
            **filters: 额外过滤条件

        Returns:
            资源总数
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
        创建资源

        Args:
            db: 数据库会话
            **kwargs: 资源属性

        Returns:
            创建的资源
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
        更新资源

        Args:
            db: 数据库会话
            resource: 资源对象
            **kwargs: 要更新的属性

        Returns:
            更新后的资源
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
        删除资源

        Args:
            db: 数据库会话
            resource: 资源对象
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
        确保用户是租户成员

        Args:
            db: 数据库会话
            tenant_id: 租户 ID
            account_id: 用户 ID

        Returns:
            成员记录

        Raises:
            HTTPException: 403 Forbidden
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
        确保用户有编辑权限

        Args:
            member: 成员记录

        Raises:
            HTTPException: 403 Forbidden
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

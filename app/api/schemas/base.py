"""
Schema 基础模型

提供所有 API Schema 的公共基类，消除重复的 Config 定义。
"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict


class OrmModel(BaseModel):
    """
    ORM 模型基类

    所有需要从数据库模型转换的 Schema 都应继承此类。
    自动启用 from_attributes 配置。
    """
    model_config = ConfigDict(from_attributes=True)


class TimestampMixin(BaseModel):
    """
    时间戳 Mixin

    提供 created_at 和 updated_at 字段。
    """
    created_at: datetime
    updated_at: Optional[datetime] = None


class OrmTimestampModel(OrmModel):
    """
    带时间戳的 ORM 模型基类

    结合 OrmModel 和 TimestampMixin 功能。
    """
    created_at: datetime
    updated_at: Optional[datetime] = None


__all__ = [
    "OrmModel",
    "TimestampMixin",
    "OrmTimestampModel",
]

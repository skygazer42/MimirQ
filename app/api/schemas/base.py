"""
Schema base models.
Provides common base classes for all API schemas, eliminating duplicate Config definitions.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class OrmModel(BaseModel):
    """
    ORM model base class.

    All schemas that need to convert from database models should inherit this class.
    Automatically enables from_attributes configuration.
    """
    model_config = ConfigDict(from_attributes=True)


class TimestampMixin(BaseModel):
    """
    Timestamp mixin.

    Provides created_at and updated_at fields.
    """
    created_at: datetime
    updated_at: datetime | None = None


class OrmTimestampModel(OrmModel):
    """
    ORM model base class with timestamps.

    Combines OrmModel and TimestampMixin functionality.
    """
    created_at: datetime
    updated_at: datetime | None = None


__all__ = [
    "OrmModel",
    "TimestampMixin",
    "OrmTimestampModel",
]

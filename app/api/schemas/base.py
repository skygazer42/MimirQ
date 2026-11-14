"""Shared Pydantic bases for ORM-backed API response models."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class OrmModel(BaseModel):
    """Enable Pydantic validation from ORM attributes."""

    model_config = ConfigDict(from_attributes=True)


class OrmTimestampModel(OrmModel):
    """Enable ORM conversion for responses that expose creation timestamps."""

    created_at: datetime
    updated_at: datetime | None = None


__all__ = [
    "OrmModel",
    "OrmTimestampModel",
]

"""
Dataset-related Pydantic schemas.
Defines data models for dataset creation, update, and query endpoints.
"""
from typing import List, Optional
from uuid import UUID
from pydantic import BaseModel, Field

from app.models.dataset import DatasetPermissionEnum
from .base import OrmModel


class DatasetBase(BaseModel):
    name: str = Field(..., max_length=255)
    description: Optional[str] = None
    permission: DatasetPermissionEnum = DatasetPermissionEnum.ALL_TEAM_MEMBERS
    partial_member_list: Optional[List[str]] = None


class DatasetCreate(DatasetBase):
    pass


class DatasetUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    permission: Optional[DatasetPermissionEnum] = None
    partial_member_list: Optional[List[str]] = None


class DatasetOut(OrmModel):
    id: UUID
    tenant_id: UUID
    name: str
    description: Optional[str]
    permission: DatasetPermissionEnum
    owner_id: Optional[str]
    partial_member_list: Optional[List[str]] = None


class DatasetListResponse(BaseModel):
    total: int
    items: List[DatasetOut]

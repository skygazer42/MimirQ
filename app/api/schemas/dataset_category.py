"""Dataset category schemas (tree + membership)."""


from uuid import UUID

from pydantic import BaseModel, Field

from .base import OrmTimestampModel


class DatasetCategoryCreate(BaseModel):
    name: str = Field(..., max_length=255)
    parent_id: UUID | None = None
    sort_order: int | None = Field(default=None, ge=0, le=1_000_000)


class DatasetCategoryUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    sort_order: int | None = Field(default=None, ge=0, le=1_000_000)


class DatasetCategoryMoveRequest(BaseModel):
    parent_id: UUID | None = None
    sort_order: int | None = Field(default=None, ge=0, le=1_000_000)


class DatasetCategoryOut(OrmTimestampModel):
    id: UUID
    tenant_id: UUID
    name: str
    parent_id: UUID | None = None
    sort_order: int = 0


class DatasetCategoryNode(BaseModel):
    id: UUID
    name: str
    parent_id: UUID | None = None
    sort_order: int = 0
    depth: int = 0
    datasets: int = 0
    children: list["DatasetCategoryNode"] = Field(default_factory=list)


class DatasetCategoryTreeResponse(BaseModel):
    total: int
    items: list[DatasetCategoryNode]


class DatasetCategoryAssignmentRequest(BaseModel):
    category_ids: list[UUID] = Field(default_factory=list)


class DatasetCategoryAssignmentResponse(BaseModel):
    dataset_id: UUID
    category_ids: list[UUID] = Field(default_factory=list)


DatasetCategoryNode.model_rebuild()

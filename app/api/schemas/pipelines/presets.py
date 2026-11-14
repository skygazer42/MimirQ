"""Request and response models for tenant chunk presets."""

from typing import Any

from pydantic import BaseModel, Field


class ChunkPresetCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=10_000)
    payload: dict[str, Any] = Field(default_factory=dict)


class ChunkPresetUpdateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=10_000)
    payload: dict[str, Any] = Field(default_factory=dict)


class ChunkPresetResponse(BaseModel):
    id: str
    name: str
    description: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class ChunkPresetListResponse(BaseModel):
    items: list[ChunkPresetResponse] = Field(default_factory=list)

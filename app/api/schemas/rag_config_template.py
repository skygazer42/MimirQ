"""
RAG config template schemas.

These templates store a partial RAG config patch (retrieval/rerank knobs) that can be
selected via template_id / template_key / ab_experiment_key (stable routing).
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field

from app.api.schemas.dataset import DatasetRAGDefaults

from .base import OrmModel


class RagConfigTemplateBase(BaseModel):
    template_key: Optional[str] = Field(
        default=None,
        max_length=100,
        description="Stable template identifier (for versioning/grouping), e.g.: retrieval_default",
        examples=["retrieval_default"],
    )
    name: str = Field(..., max_length=200, description="Human-readable name for the template")
    description: Optional[str] = Field(default=None, description="Optional detailed description of the template")

    config_patch: DatasetRAGDefaults = Field(
        default_factory=DatasetRAGDefaults,
        description="Partial RAG config patch (retrieval/rerank knobs). Only provided fields are applied.",
    )

    is_active: bool = Field(default=True, description="Whether this template is enabled")

    version: Optional[int] = Field(default=1, ge=1, description="Version number (increments within same template_key)")
    parent_id: Optional[UUID] = Field(default=None, description="Parent version template ID (optional)")

    ab_experiment_key: Optional[str] = Field(
        default=None,
        max_length=100,
        description="A/B experiment key (optional), e.g.: exp_2026w10_rerank",
    )
    ab_variant: Optional[str] = Field(default=None, max_length=50, description="A/B variant label (optional), e.g.: A/B")
    ab_weight: Optional[float] = Field(default=1.0, ge=0.0, description="A/B traffic weight (optional, default 1.0)")


class RagConfigTemplateCreate(RagConfigTemplateBase):
    pass


class RagConfigTemplateUpdate(BaseModel):
    template_key: Optional[str] = Field(default=None, max_length=100)
    name: Optional[str] = Field(default=None, max_length=200)
    description: Optional[str] = None
    config_patch: Optional[DatasetRAGDefaults] = None
    is_active: Optional[bool] = None
    version: Optional[int] = Field(default=None, ge=1)
    parent_id: Optional[UUID] = None
    ab_experiment_key: Optional[str] = Field(default=None, max_length=100)
    ab_variant: Optional[str] = Field(default=None, max_length=50)
    ab_weight: Optional[float] = Field(default=None, ge=0.0)


class RagConfigTemplateNewVersion(BaseModel):
    """Create a new version from an existing template (copy + optional overrides)."""

    name: Optional[str] = Field(default=None, max_length=200)
    description: Optional[str] = None
    config_patch: Optional[DatasetRAGDefaults] = None
    is_active: bool = True
    deactivate_previous: bool = Field(default=True, description="Auto-deactivate previous versions for the same key")

    ab_experiment_key: Optional[str] = Field(default=None, max_length=100)
    ab_variant: Optional[str] = Field(default=None, max_length=50)
    ab_weight: float = Field(default=1.0, ge=0.0)


class RagConfigTemplateOut(OrmModel):
    id: UUID
    tenant_id: UUID
    template_key: Optional[str]
    name: str
    description: Optional[str]
    config_patch: DatasetRAGDefaults
    is_active: bool
    usage_count: int
    version: int
    parent_id: Optional[UUID]
    ab_experiment_key: Optional[str]
    ab_variant: Optional[str]
    ab_weight: float
    created_at: datetime
    updated_at: datetime


class RagConfigTemplateList(BaseModel):
    total: int = Field(..., description="Total number of templates matching filters")
    items: List[RagConfigTemplateOut] = Field(..., description="List of RAG config templates")


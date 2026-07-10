"""
RAG config template schemas.

These templates store a partial RAG config patch (retrieval/rerank knobs) that can be
selected via template_id / template_key / ab_experiment_key (stable routing).
"""


from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.api.schemas.dataset import DatasetRAGDefaults

from .base import OrmModel


class RagConfigTemplateBase(BaseModel):
    template_key: str | None = Field(
        default=None,
        max_length=100,
        description="Stable template identifier (for versioning/grouping), e.g.: retrieval_default",
        examples=["retrieval_default"],
    )
    name: str = Field(..., max_length=200, description="Human-readable name for the template")
    description: str | None = Field(default=None, description="Optional detailed description of the template")

    config_patch: DatasetRAGDefaults = Field(
        default_factory=DatasetRAGDefaults,
        description="Partial RAG config patch (retrieval/rerank knobs). Only provided fields are applied.",
    )

    is_active: bool = Field(default=True, description="Whether this template is enabled")

    version: int | None = Field(default=1, ge=1, description="Version number (increments within same template_key)")
    parent_id: UUID | None = Field(default=None, description="Parent version template ID (optional)")

    ab_experiment_key: str | None = Field(
        default=None,
        max_length=100,
        description="A/B experiment key (optional), e.g.: exp_2026w10_rerank",
    )
    ab_variant: str | None = Field(default=None, max_length=50, description="A/B variant label (optional), e.g.: A/B")
    ab_weight: float | None = Field(default=1.0, ge=0.0, description="A/B traffic weight (optional, default 1.0)")


class RagConfigTemplateCreate(RagConfigTemplateBase):
    pass


class RagConfigTemplateUpdate(BaseModel):
    template_key: str | None = Field(default=None, max_length=100)
    name: str | None = Field(default=None, max_length=200)
    description: str | None = None
    config_patch: DatasetRAGDefaults | None = None
    is_active: bool | None = None
    version: int | None = Field(default=None, ge=1)
    parent_id: UUID | None = None
    ab_experiment_key: str | None = Field(default=None, max_length=100)
    ab_variant: str | None = Field(default=None, max_length=50)
    ab_weight: float | None = Field(default=None, ge=0.0)


class RagConfigTemplateNewVersion(BaseModel):
    """Create a new version from an existing template (copy + optional overrides)."""

    name: str | None = Field(default=None, max_length=200)
    description: str | None = None
    config_patch: DatasetRAGDefaults | None = None
    is_active: bool = True
    deactivate_previous: bool = Field(default=True, description="Auto-deactivate previous versions for the same key")

    ab_experiment_key: str | None = Field(default=None, max_length=100)
    ab_variant: str | None = Field(default=None, max_length=50)
    ab_weight: float = Field(default=1.0, ge=0.0)


class RagConfigTemplateOut(OrmModel):
    id: UUID
    tenant_id: UUID
    template_key: str | None
    name: str
    description: str | None
    config_patch: DatasetRAGDefaults
    is_active: bool
    usage_count: int
    version: int
    parent_id: UUID | None
    ab_experiment_key: str | None
    ab_variant: str | None
    ab_weight: float
    created_at: datetime
    updated_at: datetime


class RagConfigTemplateList(BaseModel):
    total: int = Field(..., description="Total number of templates matching filters")
    items: list[RagConfigTemplateOut] = Field(..., description="List of RAG config templates")


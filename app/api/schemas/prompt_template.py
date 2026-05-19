"""
Prompt template schemas.
Defines data models for prompt template creation, update, and query endpoints.
"""
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from .base import OrmModel


class PromptTemplateBase(BaseModel):
    """Base schema containing common prompt template fields."""

    template_key: str | None = Field(
        default=None,
        max_length=100,
        description="Stable template identifier (for versioning/grouping), e.g.: kb_assistant",
        json_schema_extra={"examples": ["kb_assistant"]},
    )
    name: str = Field(
        ...,
        max_length=200,
        description="Human-readable name for the template",
        json_schema_extra={"examples": ["Legal Consultant"]},
    )
    description: str | None = Field(
        None,
        description="Optional detailed description of template purpose",
        json_schema_extra={"examples": ["A template for legal advice and consultation"]},
    )
    content: str = Field(
        ...,
        description="The prompt template content with variable placeholders",
        json_schema_extra={"examples": ["You are a legal consultant. Context: {context}\n\nQuestion: {question}"]},
    )
    variables: list[str] = Field(
        default_factory=list,
        description="List of variable names supported in the template",
        json_schema_extra={"examples": [["context", "question", "history"]]},
    )
    category: str | None = Field(
        None,
        max_length=100,
        description="Category for organizing templates",
        json_schema_extra={"examples": ["legal"]},
    )
    tags: list[str] = Field(
        default_factory=list,
        description="Tags for searchability and filtering",
        json_schema_extra={"examples": [["expert", "formal", "detailed"]]},
    )
    is_active: bool = Field(
        True,
        description="Whether this template is currently enabled"
    )
    version: int | None = Field(
        default=1,
        ge=1,
        description="Version number (increments within same template_key)",
    )
    parent_id: UUID | None = Field(default=None, description="Parent version template ID (optional)")
    ab_experiment_key: str | None = Field(
        default=None,
        max_length=100,
        description="A/B experiment identifier (optional), e.g.: exp_2025w50",
    )
    ab_variant: str | None = Field(default=None, max_length=50, description="A/B variant identifier (optional), e.g.: A/B")
    ab_weight: float | None = Field(default=1.0, ge=0.0, description="A/B traffic weight (optional, default 1.0)")


class PromptTemplateCreate(PromptTemplateBase):
    """Schema for creating a new prompt template."""

    pass


class PromptTemplateUpdate(BaseModel):
    """Schema for updating an existing prompt template (all fields optional)."""

    template_key: str | None = Field(None, max_length=100)
    name: str | None = Field(None, max_length=200)
    description: str | None = None
    content: str | None = None
    variables: list[str] | None = None
    category: str | None = Field(None, max_length=100)
    tags: list[str] | None = None
    is_active: bool | None = None
    version: int | None = Field(default=None, ge=1)
    parent_id: UUID | None = None
    ab_experiment_key: str | None = Field(None, max_length=100)
    ab_variant: str | None = Field(None, max_length=50)
    ab_weight: float | None = Field(default=None, ge=0.0)


class PromptTemplateNewVersion(BaseModel):
    """Create a new version (copy from old template, supports field overrides)."""

    name: str | None = Field(None, max_length=200)
    description: str | None = None
    content: str | None = None
    variables: list[str] | None = None
    category: str | None = Field(None, max_length=100)
    tags: list[str] | None = None
    is_active: bool = True
    deactivate_previous: bool = Field(default=True, description="Auto-deactivate previous version (default: true)")

    ab_experiment_key: str | None = Field(None, max_length=100)
    ab_variant: str | None = Field(None, max_length=50)
    ab_weight: float = Field(default=1.0, ge=0.0)


class PromptTemplateOut(OrmModel):
    """Schema for prompt template responses with all database fields."""

    id: UUID
    tenant_id: UUID
    template_key: str | None
    name: str
    description: str | None
    content: str
    variables: list[str]
    is_system: bool
    is_active: bool
    category: str | None
    tags: list[str]
    usage_count: int
    version: int
    parent_id: UUID | None
    ab_experiment_key: str | None
    ab_variant: str | None
    ab_weight: float
    created_at: datetime
    updated_at: datetime


class PromptTemplateList(BaseModel):
    """Schema for paginated list of prompt templates."""

    total: int = Field(..., description="Total number of templates matching filters")
    items: list[PromptTemplateOut] = Field(..., description="List of prompt templates")


class BuiltinPromptTemplateSyncResponse(BaseModel):
    """Result of synchronizing built-in prompt templates into the current tenant."""

    created: int = Field(..., ge=0, description="Number of built-in templates created")
    updated: int = Field(..., ge=0, description="Number of existing built-in templates updated")
    template_keys: list[str] = Field(..., description="Synchronized built-in template keys")

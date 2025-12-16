"""
Pydantic schemas for prompt template API requests and responses.

This module defines the data validation and serialization schemas
for prompt template operations using Pydantic models.
"""
from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class PromptTemplateBase(BaseModel):
    """Base schema containing common prompt template fields."""

    name: str = Field(
        ...,
        max_length=200,
        description="Human-readable name for the template",
        example="Legal Consultant"
    )
    description: Optional[str] = Field(
        None,
        description="Optional detailed description of template purpose",
        example="A template for legal advice and consultation"
    )
    content: str = Field(
        ...,
        description="The prompt template content with variable placeholders",
        example="You are a legal consultant. Context: {context}\n\nQuestion: {question}"
    )
    variables: List[str] = Field(
        default_factory=list,
        description="List of variable names supported in the template",
        example=["context", "question", "history"]
    )
    category: Optional[str] = Field(
        None,
        max_length=100,
        description="Category for organizing templates",
        example="legal"
    )
    tags: List[str] = Field(
        default_factory=list,
        description="Tags for searchability and filtering",
        example=["expert", "formal", "detailed"]
    )
    is_active: bool = Field(
        True,
        description="Whether this template is currently enabled"
    )


class PromptTemplateCreate(PromptTemplateBase):
    """Schema for creating a new prompt template."""

    pass


class PromptTemplateUpdate(BaseModel):
    """Schema for updating an existing prompt template (all fields optional)."""

    name: Optional[str] = Field(None, max_length=200)
    description: Optional[str] = None
    content: Optional[str] = None
    variables: Optional[List[str]] = None
    category: Optional[str] = Field(None, max_length=100)
    tags: Optional[List[str]] = None
    is_active: Optional[bool] = None


class PromptTemplateOut(BaseModel):
    """Schema for prompt template responses with all database fields."""

    id: UUID
    tenant_id: UUID
    name: str
    description: Optional[str]
    content: str
    variables: List[str]
    is_system: bool
    is_active: bool
    category: Optional[str]
    tags: List[str]
    usage_count: int
    created_at: datetime
    updated_at: datetime

    class Config:
        """Pydantic configuration."""

        from_attributes = True


class PromptTemplateList(BaseModel):
    """Schema for paginated list of prompt templates."""

    total: int = Field(..., description="Total number of templates matching filters")
    items: List[PromptTemplateOut] = Field(..., description="List of prompt templates")

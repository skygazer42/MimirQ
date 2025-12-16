"""
Pydantic schemas for prompt templates.
"""
from typing import List, Optional
from uuid import UUID
from datetime import datetime
from pydantic import BaseModel, Field


class PromptTemplateBase(BaseModel):
    name: str = Field(..., max_length=200, description="Template name")
    description: Optional[str] = Field(None, description="Template description")
    content: str = Field(..., description="Prompt template content")
    variables: List[str] = Field(default_factory=list, description="Supported variables (e.g., ['context', 'question', 'history'])")
    category: Optional[str] = Field(None, max_length=100, description="Template category")
    tags: List[str] = Field(default_factory=list, description="Template tags")
    is_active: bool = Field(True, description="Whether the template is active")


class PromptTemplateCreate(PromptTemplateBase):
    pass


class PromptTemplateUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=200)
    description: Optional[str] = None
    content: Optional[str] = None
    variables: Optional[List[str]] = None
    category: Optional[str] = Field(None, max_length=100)
    tags: Optional[List[str]] = None
    is_active: Optional[bool] = None


class PromptTemplateOut(BaseModel):
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
        from_attributes = True


class PromptTemplateList(BaseModel):
    total: int
    items: List[PromptTemplateOut]

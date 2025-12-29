"""
提示词模板相关 Schema
定义提示词模板的创建、更新、查询等接口的数据模型。
"""
from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field

from .base import OrmModel


class PromptTemplateBase(BaseModel):
    """Base schema containing common prompt template fields."""

    template_key: Optional[str] = Field(
        default=None,
        max_length=100,
        description="模板稳定标识（用于版本化/分组），例如：kb_assistant",
        example="kb_assistant",
    )
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
    version: Optional[int] = Field(
        default=1,
        ge=1,
        description="版本号（同一 template_key 内递增）",
    )
    parent_id: Optional[UUID] = Field(default=None, description="父版本模板 ID（可选）")
    ab_experiment_key: Optional[str] = Field(
        default=None,
        max_length=100,
        description="A/B 实验标识（可选），例如：exp_2025w50",
    )
    ab_variant: Optional[str] = Field(default=None, max_length=50, description="A/B 变体标识（可选），例如 A/B")
    ab_weight: Optional[float] = Field(default=1.0, ge=0.0, description="A/B 流量权重（可选，默认 1.0）")


class PromptTemplateCreate(PromptTemplateBase):
    """Schema for creating a new prompt template."""

    pass


class PromptTemplateUpdate(BaseModel):
    """Schema for updating an existing prompt template (all fields optional)."""

    template_key: Optional[str] = Field(None, max_length=100)
    name: Optional[str] = Field(None, max_length=200)
    description: Optional[str] = None
    content: Optional[str] = None
    variables: Optional[List[str]] = None
    category: Optional[str] = Field(None, max_length=100)
    tags: Optional[List[str]] = None
    is_active: Optional[bool] = None
    version: Optional[int] = Field(default=None, ge=1)
    parent_id: Optional[UUID] = None
    ab_experiment_key: Optional[str] = Field(None, max_length=100)
    ab_variant: Optional[str] = Field(None, max_length=50)
    ab_weight: Optional[float] = Field(default=None, ge=0.0)


class PromptTemplateNewVersion(BaseModel):
    """创建新版本（基于旧模板复制，支持覆盖字段）。"""

    name: Optional[str] = Field(None, max_length=200)
    description: Optional[str] = None
    content: Optional[str] = None
    variables: Optional[List[str]] = None
    category: Optional[str] = Field(None, max_length=100)
    tags: Optional[List[str]] = None
    is_active: bool = True
    deactivate_previous: bool = Field(default=True, description="是否自动禁用旧版本（默认 true）")

    ab_experiment_key: Optional[str] = Field(None, max_length=100)
    ab_variant: Optional[str] = Field(None, max_length=50)
    ab_weight: float = Field(default=1.0, ge=0.0)


class PromptTemplateOut(OrmModel):
    """Schema for prompt template responses with all database fields."""

    id: UUID
    tenant_id: UUID
    template_key: Optional[str]
    name: str
    description: Optional[str]
    content: str
    variables: List[str]
    is_system: bool
    is_active: bool
    category: Optional[str]
    tags: List[str]
    usage_count: int
    version: int
    parent_id: Optional[UUID]
    ab_experiment_key: Optional[str]
    ab_variant: Optional[str]
    ab_weight: float
    created_at: datetime
    updated_at: datetime


class PromptTemplateList(BaseModel):
    """Schema for paginated list of prompt templates."""

    total: int = Field(..., description="Total number of templates matching filters")
    items: List[PromptTemplateOut] = Field(..., description="List of prompt templates")

"""
Prompt template models for customizable RAG prompts.

This module defines the database model for storing and managing
prompt templates that can be used to customize RAG system behavior.
"""
import uuid
from typing import List

from sqlalchemy import Boolean, Column, DateTime, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.sql import func

from app.core.database import Base


class PromptTemplate(Base):
    """
    Prompt template model for RAG system.

    Stores customizable prompt templates that define how the RAG system
    interacts with users. Supports variables, categorization, and usage tracking.

    Attributes:
        id: Unique identifier for the template
        tenant_id: ID of the tenant that owns this template
        name: Human-readable name for the template
        description: Optional detailed description
        content: The actual prompt template text with variable placeholders
        variables: List of supported variable names (e.g., ["context", "question"])
        is_system: Whether this is a system-provided template (immutable)
        is_active: Whether this template is currently enabled
        category: Optional category for organizing templates
        tags: List of tags for searchability and filtering
        usage_count: Number of times this template has been used
        created_at: Timestamp when template was created
        updated_at: Timestamp when template was last modified
    """

    __tablename__ = "prompt_templates"

    # Primary key and tenant isolation
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)

    # Basic template information
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    content = Column(Text, nullable=False)

    # Template configuration
    variables = Column(JSONB, default=list)  # Supported variable names
    is_system = Column(Boolean, default=False)  # Immutable system template
    is_active = Column(Boolean, default=True)  # Enable/disable template

    # Organization and discovery
    category = Column(String(100), nullable=True)
    tags = Column(JSONB, default=list)

    # Analytics
    usage_count = Column(Integer, default=0)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now()
    )

    # Composite indexes for common query patterns
    __table_args__ = (
        Index("ix_prompt_templates_tenant_name", "tenant_id", "name"),
        Index("ix_prompt_templates_tenant_active", "tenant_id", "is_active"),
        Index("ix_prompt_templates_tenant_system", "tenant_id", "is_system"),
    )

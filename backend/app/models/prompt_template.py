"""
Prompt template models for customizable RAG prompts.
"""
import uuid
from sqlalchemy import Column, String, Text, Boolean, DateTime, Integer, Index
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func

from app.core.database import Base


class PromptTemplate(Base):
    """Prompt template table for RAG system prompts"""
    __tablename__ = "prompt_templates"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)

    # Template identification
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)

    # Prompt content
    content = Column(Text, nullable=False)

    # Variables supported in this template (e.g., ["context", "question", "history"])
    variables = Column(JSONB, default=list)

    # System and activation flags
    is_system = Column(Boolean, default=False)  # System default template
    is_active = Column(Boolean, default=True)   # User can activate/deactivate

    # Category/tags for organization
    category = Column(String(100), nullable=True)  # e.g., "legal", "technical", "casual"
    tags = Column(JSONB, default=list)  # e.g., ["expert", "concise"]

    # Usage tracking
    usage_count = Column(Integer, default=0)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index('ix_prompt_templates_tenant_name', 'tenant_id', 'name'),
        Index('ix_prompt_templates_tenant_active', 'tenant_id', 'is_active'),
        Index('ix_prompt_templates_tenant_system', 'tenant_id', 'is_system'),
    )

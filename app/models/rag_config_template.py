"""
RAG config template data model.

Provides versioned, tenant-scoped configuration patches for retrieval/rerank knobs,
including A/B experiment routing fields (ab_experiment_key/ab_variant/ab_weight).

Design goals:
- Low-cardinality selectors for safe rollout/rollback
- PII-safe payloads (no raw query/doc content)
"""


import uuid

from sqlalchemy import Boolean, Column, DateTime, Float, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.sql import func

from app.core.database import Base


class RagConfigTemplate(Base):
    """
    RAG config template model.

    Stores a JSON patch (subset of ChatRAGConfig / DatasetRAGDefaults fields) that can be applied
    at runtime based on:
    - explicit template_id
    - latest version by template_key
    - A/B experiment routing by ab_experiment_key + weights
    """

    __tablename__ = "rag_config_templates"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)

    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)

    # A partial config patch (best-effort: only validated/used keys are applied).
    config_patch = Column(JSONB, default=dict, nullable=False)

    # Enable/disable without deleting.
    is_active = Column(Boolean, default=True)

    # Analytics (best-effort).
    usage_count = Column(Integer, default=0)

    # Versioning & A/B testing (mirrors PromptTemplate patterns).
    template_key = Column(String(100), nullable=True, index=True)
    version = Column(Integer, default=1)
    parent_id = Column(UUID(as_uuid=True), nullable=True)
    ab_experiment_key = Column(String(100), nullable=True, index=True)
    ab_variant = Column(String(50), nullable=True)
    ab_weight = Column(Float, default=1.0)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("ix_rag_config_templates_tenant_name", "tenant_id", "name"),
        Index("ix_rag_config_templates_tenant_active", "tenant_id", "is_active"),
        Index("ix_rag_config_templates_tenant_template_key_version", "tenant_id", "template_key", "version"),
        Index("ix_rag_config_templates_tenant_ab_experiment", "tenant_id", "ab_experiment_key"),
    )


__all__ = ["RagConfigTemplate"]

